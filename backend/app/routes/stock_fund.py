"""
股票资金桥接端点（v1.3.0 跨库一致性）
======================================
背景：双 SQLite（gipfel.db 区域账户 + stocks.db 用户余额）资金独立。
用户拍板「打通」：股票买卖资金从区域账户扣/加。

本模块是 gipfel-api 侧的「资金桥」——stock-api 买卖时调用本端点：
  POST /api/stock/fund  原子扣/加用户映射的区域账户余额（防透支）
  GET  /api/stock/fund?username=  查询用户当前可用资金（区域账户映射）

跨库一致性设计（无分布式事务，用「先扣款后记账 + 补偿 + 幂等」）：
  1. stock-api 买入：先调本端点扣款（写 account_transactions 流水，idempotency_key=订单号）
  2. 扣款成功 → stock-api 本地写 orders/portfolios
  3. 若 2 失败 → stock-api 调本端点冲正（同 idempotency_key → 幂等，不重复扣/加）
  4. 卖出同理反向（先加款）
  5. 幂等：idempotency_key 已处理过 → 直接返回首次结果，不重复执行

用户→区域账户映射：
  user.company_id → companies.region（如 "A区"）→ regions.name → region_accounts.region_id
  admin / 未绑定公司 → 默认 A区账户（region_id=1）
"""
import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user_optional
from ..database import get_db, commit_with_retry
from ..models.all_models import User, Company, Region, RegionAccount, AccountTransaction

router = APIRouter(prefix="/api/stock", tags=["股票资金桥"])

# 幂等记录：idempotency_key → {"result": ..., "ts": ...}（进程内；重启后首次请求重新执行——
# 但流水表本身有唯一索引防重复，见下方 check）
_STOCK_FUND_KEYS: dict = {}

# 默认区域（admin / 未绑定用户）
DEFAULT_REGION_ID = 1


def _resolve_region_account(db: Session, username: str):
    """用户 → 区域账户（云端：user.org_id → company.org_id → company.region → regions.id → region_accounts）
    admin / 默认组织（无对应公司）→ 默认 A区账户"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    region_id = None
    if user.org_id:
        company = db.query(Company).filter(Company.org_id == user.org_id).first()
        if company and company.region:
            region = db.query(Region).filter(Region.name == company.region).first()
            if region:
                region_id = region.id
    if region_id is None:
        region_id = DEFAULT_REGION_ID
    acct = db.query(RegionAccount).filter(
        RegionAccount.region_id == region_id, RegionAccount.is_master == 1).first()
    if not acct:
        acct = db.query(RegionAccount).filter(RegionAccount.region_id == region_id).first()
    if not acct:
        raise HTTPException(500, f"区域 {region_id} 无资金账户，请联系管理员")
    return user, acct


class StockFundReq:
    """POST body（用 dict 解析，避免 Pydantic 版本差异）"""


@router.post("/fund")
def stock_fund_transaction(req_body: dict,
                           request: Request,
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user_optional)):
    """股票资金扣/加（跨库桥核心）。

    body: {
      "username": "admin",
      "side": "buy" | "sell",          # buy=扣款(支出), sell=加款(收入)
      "amount": 1000.0,
      "idempotency_key": "order-uuid"   # 幂等键（订单号）
    }
    返回: {"success": true, "balance": 当前余额, "account_id": n}

    鉴权：优先 JWT（get_current_user_optional）；无 JWT 时校验 X-Internal-Key
    （与 ADMIN_KEY 同源）——允许 stock-api 本机回环调用。
    """
    # 内部密钥校验（stock-api 回环调用无 JWT）
    internal_key = request.headers.get("X-Internal-Key", "")
    expected_key = os.environ.get("ADMIN_KEY", "gipfel-admin-dev")
    if not user and internal_key != expected_key:
        raise HTTPException(401, "未认证：需要登录或内部密钥")
    try:
        username = str(req_body.get("username") or "").strip()
        side = str(req_body.get("side") or "").strip().lower()
        amount = float(req_body.get("amount") or 0)
        idem_key = str(req_body.get("idempotency_key") or "").strip()
    except (TypeError, ValueError):
        raise HTTPException(400, "参数格式错误")
    if not username or not side or side not in ("buy", "sell"):
        raise HTTPException(400, "username / side(buy|sell) 必填")
    if amount <= 0:
        raise HTTPException(400, "amount 必须大于 0")
    if not idem_key:
        raise HTTPException(400, "idempotency_key 必填（幂等防重复）")

    # ── 幂等（DB 级）：流水 INSERT 带 idempotency_key（部分唯一索引）──
    # 并发同 key：两个事务同时尝试 INSERT → 一个成功一个 IntegrityError →
    # 失败者回滚后查已有流水返回原结果（不重复扣款）。内存字典仅作快速路径。
    if idem_key in _STOCK_FUND_KEYS:
        return _STOCK_FUND_KEYS[idem_key]

    user, acct = _resolve_region_account(db, username)
    trans_type = "expense" if side == "buy" else "income"
    category = "股票买入" if side == "buy" else "股票卖出"

    # ── 扣款防透支（原子 UPDATE + 余额守卫）──
    if side == "buy":
        res = db.execute(
            sa_text("UPDATE region_accounts SET balance = balance - :a "
                    "WHERE id = :id AND balance >= :a"),
            {"a": amount, "id": acct.id})
        if res.rowcount == 0:
            raise HTTPException(400, f"资金不足：账户余额 {(acct.balance or 0):.2f} 不足以支付 ¥{amount:.2f}")
    else:
        db.execute(
            sa_text("UPDATE region_accounts SET balance = balance + :a WHERE id = :id"),
            {"a": amount, "id": acct.id})

    # ── 流水留痕（idempotency_key 唯一——DB 级幂等防重复）──
    db.add(AccountTransaction(
        account_id=acct.id,
        trans_type=trans_type,
        category=category,
        amount=amount,
        description=f"股票{category} · {username} · {idem_key}",
        fiscal_year=datetime.utcnow().year,
        operator=username,
        source_type="stock",
        idempotency_key=idem_key,
    ))
    try:
        commit_with_retry(db)
    except IntegrityError:
        # 并发同 key：唯一索引冲突 → 本事务回滚（余额未动），返回首次处理结果
        db.rollback()
        existing = db.query(AccountTransaction).filter(
            AccountTransaction.idempotency_key == idem_key).first()
        if existing:
            return {"success": True, "balance": round(float(acct.balance or 0), 2),
                    "account_id": acct.id, "idempotency_key": idem_key,
                    "deduplicated": True}
        raise HTTPException(500, "资金处理冲突，请重试")
    db.refresh(acct)

    result = {"success": True, "balance": round(float(acct.balance or 0), 2),
              "account_id": acct.id, "idempotency_key": idem_key}
    _STOCK_FUND_KEYS[idem_key] = result
    return result


@router.get("/fund")
def stock_fund_query(username: str, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user_optional)):
    """查询用户可用资金（区域账户映射余额）——支持 JWT 或 X-Internal-Key"""
    internal_key = request.headers.get("X-Internal-Key", "")
    expected_key = os.environ.get("ADMIN_KEY", "gipfel-admin-dev")
    if not user and internal_key != expected_key:
        raise HTTPException(401, "未认证：需要登录或内部密钥")
    _, acct = _resolve_region_account(db, username)
    return {"success": True, "username": username, "balance": round(float(acct.balance or 0), 2),
            "account_id": acct.id, "account_name": acct.account_name}
