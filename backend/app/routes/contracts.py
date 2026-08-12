"""合同 CRUD + 审批 + 版本历史 + 区域汇总

P0-1 修复：补齐桌面端 cloudApi ROUTE_MAP 指向的缺失路由：
  - PUT/PATCH /api/contracts/{id}            （contract:update）
  - POST /api/contracts/{id}/approve         （contract:approve）
  - POST /api/contracts/batch-approve        （contract:batch-approve）
  - GET  /api/contracts/{id}/versions        （contract:list-versions）
P0-2 修复：Contract/ContractItem 补字段，list/detail 返回 items 与计算字段。
P0-3 修复：明细税/合计按「税率=百分比」口径计算（与桌面端 v20 一致）。
"""
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db, commit_with_retry
from ..models import (
    Company, Contract, ContractItem, ContractType, ContractVersion, Region,
    RegionAccount, AccountTransaction, User,
)
from ..services.audit import insert_audit_log
from ..services.notify import notify_admins, notify_user_by_username

router = APIRouter()


# ── Pydantic 模型 ──────────────────────────────────
class ItemData(BaseModel):
    item_name: str
    quantity: float = 1
    unit_price: float = 0
    land_area: float = 0
    tax_rate: float = 0
    skill_level: float = 0
    carbon_factor: float = 0
    total_cost: Optional[float] = None   # 投资金额（原总成本）
    expected_income: Optional[float] = None
    # ── v1.3.1 金融化投资项目字段（Optional：未传=None → 云端继承旧值防清空）──
    investment_type: Optional[str] = None
    equity_ratio: Optional[float] = None
    expected_return_rate: Optional[float] = None
    investment_period: Optional[str] = None


class ContractCreate(BaseModel):
    contract_name: str
    contract_type_id: Optional[int] = None
    party_a: str = ""
    party_b_name: str = ""
    party_b_id: Optional[int] = None
    region_id: Optional[int] = None
    sign_date: Optional[str] = None
    status: str = "active"  # v1.3.1 金融化：创建即生效，无审批流
    notes: str = ""
    items: List[ItemData] = []
    # ── v1.3.1 金融化新字段 ──
    contract_amount: Optional[float] = None   # 合同金额（总投资额）
    contract_period: str = ""                # 合同期限
    owner: str = ""                          # 负责人
    attachment: str = ""                     # 附件名/路径


class ContractUpdate(BaseModel):
    contract_name: Optional[str] = None
    contract_type_id: Optional[int] = None
    party_a: Optional[str] = None
    party_b_name: Optional[str] = None
    party_b_id: Optional[int] = None
    region_id: Optional[int] = None
    sign_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    total_cost: Optional[float] = None
    progress: Optional[float] = None
    expected_income: Optional[float] = None
    items: Optional[List[ItemData]] = None
    # ── v1.3.1 金融化新字段 ──
    contract_amount: Optional[float] = None
    contract_period: Optional[str] = None
    owner: Optional[str] = None
    attachment: Optional[str] = None
    # ── v1.3.0 乐观锁：可选。前端传 expected_version 时，若与当前版本不符 → 409（并发编辑冲突）──
    expected_version: Optional[int] = None


class ApproveReq(BaseModel):
    action: str  # submit / approve / reject
    operator: Optional[str] = None  # 仅兼容桌面端透传，实际以登录用户为准


class BatchApproveReq(BaseModel):
    ids: List[int]
    action: str  # submit / approve / delete
    operator: Optional[str] = None


# ── 常量与状态机（v1.3.1 金融化：草稿/有效/执行中/完成/终止，无审批）──
CONTRACT_STATUSES = ["draft", "active", "executing", "completed", "terminated"]
STATUS_TRANSITIONS = {
    "draft": ["active", "terminated"],
    "active": ["executing", "terminated"],
    "executing": ["completed", "terminated"],
    "completed": [],
    "terminated": [],
}

VERSION_SNAPSHOT_FIELDS = [
    "contract_no", "contract_name", "contract_type_id", "contract_type_name",
    "party_a", "party_b_id", "party_b_name", "company_name",
    "region_id", "region_name", "sign_date", "status", "notes",
    "total_cost", "progress", "expected_income",
    "contract_amount", "contract_period", "owner", "attachment",
]


def _validate_status_transition(old_status, new_status, approval_status=None) -> Optional[str]:
    """校验 status 流转合法性；合法返回 None，非法返回错误信息（中文）。
    v1.3.1：审批参数保留兼容调用，不再参与校验（审批流已废弃）。"""
    if new_status is None or new_status == old_status:
        return None
    old_status = old_status or ""
    if new_status not in CONTRACT_STATUSES:
        return f"非法状态：{new_status}（允许：{' / '.join(CONTRACT_STATUSES)}）"
    if old_status and old_status not in CONTRACT_STATUSES:
        return f"合同当前状态异常：{old_status}，无法流转"
    if new_status not in STATUS_TRANSITIONS.get(old_status, []):
        return f"不允许的状态流转：{old_status or '（空）'} → {new_status}（允许：草稿→有效→执行中→完成/终止）"
    return None


# ── 金额计算（P0-3：税率按百分比；对齐桌面端 computeContractAmounts）──
def _compute_amounts(contract_type_id, items: List[ItemData]):
    """H2/H3 修复（2026-08-11 业务审核）：与桌面端 contract.repo.ts 口径统一——
    显式金额必须 >0 才采用（0 视为未录入走推算），防 DB 存 0 绕过推算击穿余额预检；
    推算 = 数量×单价×(1+税率/100)。"""
    total_cost = 0.0
    expected_income = 0.0
    for it in items or []:
        qty = it.quantity if it.quantity is not None else 1
        price = it.unit_price if it.unit_price is not None else 0
        tax = it.tax_rate if it.tax_rate is not None else 0
        # 显式录入金额且 >0 优先；0 或 None 一律按 数量×单价×(1+税率/100) 推算
        item_cost = it.total_cost if (it.total_cost is not None and it.total_cost > 0) \
            else qty * price * (1 + tax / 100)
        item_income = it.expected_income if (it.expected_income is not None and it.expected_income > 0) \
            else (qty * price if contract_type_id == 7 else 0)
        total_cost += item_cost
        expected_income += item_income
    return round(total_cost, 2), round(expected_income, 2)


# ── 序列化 ────────────────────────────────────────
def _fmt_dt(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return v


def _serialize_item(it: ContractItem) -> dict:
    return {
        "id": it.id,
        "contract_id": it.contract_id,
        "item_name": it.item_name,
        "quantity": it.quantity,
        "unit_price": it.unit_price,
        "amount": round(it.amount, 2),
        "land_area": it.land_area,
        "total_land_area": round(it.total_land_area, 2),
        "tax_rate": it.tax_rate,
        "tax_amount": it.tax_amount,
        "total": round(it.total, 2),
        "sort_order": it.sort_order,
        "skill_level": it.skill_level,
        "carbon_factor": it.carbon_factor,
        "total_cost": it.total_cost,
        "expected_income": it.expected_income,
        # v1.3.1 金融化投资字段
        "investment_type": it.investment_type or "",
        "equity_ratio": it.equity_ratio or 0,
        "expected_return_rate": it.expected_return_rate or 0,
        "investment_period": it.investment_period or "",
    }


def _serialize_contract(contract: Contract, ct_name=None, region_name=None, company_name=None, items=None) -> dict:
    result = {col.name: getattr(contract, col.name) for col in Contract.__table__.columns}
    result["contract_type_name"] = ct_name
    result["region_name"] = region_name
    result["company_name"] = company_name
    result["created_at"] = _fmt_dt(result.get("created_at"))
    result["updated_at"] = _fmt_dt(result.get("updated_at"))
    result["approved_at"] = _fmt_dt(result.get("approved_at"))
    result["items"] = [_serialize_item(i) for i in (items if items is not None else contract.items)]
    return result


def _contract_row(db: Session, contract: Contract):
    """联表取展示名（含 items 的完整 dict，供快照/序列化）。"""
    ct_name = db.query(ContractType.name).filter(ContractType.id == contract.contract_type_id).scalar() if contract.contract_type_id else None
    region_name = db.query(Region.name).filter(Region.id == contract.region_id).scalar() if contract.region_id else None
    company_name = db.query(Company.name).filter(Company.id == contract.party_b_id).scalar() if contract.party_b_id else None
    return _serialize_contract(contract, ct_name, region_name, company_name)


# ── 版本快照（对齐桌面端 buildSnapshot / saveVersionSnapshot）──
def _build_snapshot(contract_dict: dict) -> dict:
    snap = {}
    for f in VERSION_SNAPSHOT_FIELDS:
        if contract_dict.get(f) is not None:
            snap[f] = contract_dict[f]
    if contract_dict.get("items"):
        snap["items"] = [
            {k: it.get(k) for k in ("item_name", "quantity", "unit_price", "land_area",
                                    "tax_rate", "skill_level", "carbon_factor",
                                    "expected_income", "total_cost",
                                    "investment_type", "equity_ratio",
                                    "expected_return_rate", "investment_period") if it.get(k) is not None}
            for it in contract_dict["items"]
        ]
    return snap


def _save_version_snapshot(db: Session, contract_id: int, contract_dict: dict, changed_fields: List[str], operator: str):
    max_v = db.query(ContractVersion.version).filter(ContractVersion.contract_id == contract_id).order_by(ContractVersion.version.desc()).first()
    version = (max_v[0] if max_v else 0) + 1
    db.add(ContractVersion(
        contract_id=contract_id,
        version=version,
        snapshot=json.dumps(_build_snapshot(contract_dict), ensure_ascii=False),
        changed_fields=json.dumps(changed_fields, ensure_ascii=False),
        created_by=operator or "",
    ))


def _changed_fields(old: dict, data: ContractUpdate) -> List[str]:
    changed = []
    for k, v in data.model_dump(exclude_unset=True).items():
        if k in ("updated_by", "created_by"):
            continue
        if k == "items":
            def _dumps_item(i):
                return i.model_dump() if hasattr(i, "model_dump") else i
            if json.dumps(old.get("items") or [], ensure_ascii=False, default=str) != json.dumps(
                [_dumps_item(i) for i in (v or [])], ensure_ascii=False, default=str
            ):
                changed.append("items")
            continue
        if str(old.get(k) if old.get(k) is not None else "") != str(v if v is not None else ""):
            changed.append(k)
    return changed


# ── 资金联动（对齐桌面端 contract.handler 的 syncContractCostToAccount）──
def _find_master_account(db: Session, region_id: int):
    return db.query(RegionAccount).filter(
        RegionAccount.region_id == region_id, RegionAccount.is_master == 1
    ).first()


def _get_or_create_master_account(db: Session, region_id: int):
    acct = _find_master_account(db, region_id)
    if acct:
        return acct
    region_name = db.query(Region.name).filter(Region.id == region_id).scalar() or ""
    acct = RegionAccount(
        region_id=region_id,
        account_name=f"{region_name or f'区域{region_id}'}主账户",
        balance=0,
        is_master=1,
    )
    db.add(acct)
    db.flush()
    return acct


def _has_contract_transaction(db: Session, contract_id: int, trans_type: str, category: str) -> bool:
    return db.query(AccountTransaction.id).filter(
        AccountTransaction.contract_id == contract_id,
        AccountTransaction.source_type == "contract",
        AccountTransaction.trans_type == trans_type,
        AccountTransaction.category == category,
    ).first() is not None


def _register_contract_expense(db: Session, contract: Contract, operator: str):
    """合同支出入账：余额不足抛 400（同一事务内，调用方回滚）。
    v1.3.0 修复：balance 改原子 UPDATE（ORM 读改写并发丢更新——曾与资金流水同 bug）。"""
    if not contract.region_id:
        return
    acct = _get_or_create_master_account(db, contract.region_id)
    amount = contract.total_cost or 0
    if amount <= 0:
        return
    balance = acct.balance or 0
    if balance < amount:
        raise HTTPException(400, f"余额不足：账户余额 {balance:.2f} 不足以支付合同支出 {amount:.2f}")
    db.add(AccountTransaction(
        account_id=acct.id,
        trans_type="expense",
        category="合同支出",
        amount=amount,
        description=f"合同 {contract.contract_name or contract.contract_no}: 合同执行",
        fiscal_year=datetime.utcnow().year,
        operator=operator,
        contract_id=contract.id,
        source_type="contract",
    ))
    # 原子扣减 + 防透支守卫（与 accounts.py add_transaction 同机制）
    from sqlalchemy import text as _sa_text
    res = db.execute(
        _sa_text("UPDATE region_accounts SET balance = balance - :a WHERE id = :id AND balance >= :a"),
        {"a": amount, "id": acct.id})
    if res.rowcount == 0:
        raise HTTPException(400, f"余额不足：无法完成合同支出 ¥{amount:.2f}")


def _register_contract_income(db: Session, contract: Contract, operator: str):
    if not contract.region_id:
        return
    acct = _get_or_create_master_account(db, contract.region_id)
    amount = contract.expected_income or 0
    if amount <= 0:
        return
    db.add(AccountTransaction(
        account_id=acct.id,
        trans_type="income",
        category="合同收入",
        amount=amount,
        description=f"合同 {contract.contract_name or contract.contract_no}: 已完成结算",
        fiscal_year=datetime.utcnow().year,
        operator=operator,
        contract_id=contract.id,
        source_type="contract",
    ))
    # v1.3.0 修复：原子增加（ORM 赋值会 dirty 覆盖原子结果）
    from sqlalchemy import text as _sa_text
    db.execute(
        _sa_text("UPDATE region_accounts SET balance = balance + :a WHERE id = :id"),
        {"a": amount, "id": acct.id})


def _notify_approval(db: Session, contract: Contract, action: str):
    try:
        if action == "submit":
            notify_admins(db, "合同待审批",
                          f"合同「{contract.contract_name or ''}」（{contract.contract_no or ''}）已提交审批，请及时处理",
                          "approval", "/contracts")
        elif action == "reject":
            notify_user_by_username(db, contract.created_by or "", "合同已驳回",
                                    f"您提交的合同「{contract.contract_name or ''}」（{contract.contract_no or ''}）已被驳回，请查看详情",
                                    "approval", "/contracts")
        elif action == "approve" and contract.approval_status == "approved":
            notify_user_by_username(db, contract.created_by or "", "合同已批准",
                                    f"您提交的合同「{contract.contract_name or ''}」（{contract.contract_no or ''}）已审批通过，请查看详情",
                                    "approval", "/contracts")
    except Exception:
        # 通知失败不影响主流程
        pass


# ═══════════════ 路由 ═══════════════

@router.get("")
def list_contracts(
    region_id: Optional[int] = Query(None),
    # 公司绑定对齐：?company_id=N 按 party_b_id 过滤（桌面端 CONTRACT_LIST companyId 的云端落点）
    company_id: Optional[int] = Query(None),
    # P1-1 分页：limit/offset 与 page/page_size 两种风格都支持；
    # 传了任一参数即返回 {items, total, page, page_size}，否则返回裸数组（兼容旧调用方）。
    limit: Optional[int] = Query(None, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    page: Optional[int] = Query(None, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """合同列表 — LEFT JOIN 返回 contract_type_name/region_name/company_name，
    P0-2：批量加载 items 随列表返回（单次 IN 查询避免 N+1）。
    H2 修复（2026-08-11 业务审核）：数据隔离——rep/user 角色强制只看本公司合同
    （user.org_id → company），忽略前端传入 company_id（防绕过）。admin/operator 看全部。"""
    q = (
        db.query(
            Contract,
            ContractType.name.label("contract_type_name"),
            Region.name.label("region_name"),
            Company.name.label("company_name"),
        )
        .outerjoin(ContractType, ContractType.id == Contract.contract_type_id)
        .outerjoin(Region, Region.id == Contract.region_id)
        .outerjoin(Company, Company.id == Contract.party_b_id)
    )
    if region_id:
        q = q.filter(Contract.region_id == region_id)
    # 公司过滤用 is not None 判断（company_id=0 也是显式值，不能用 truthy）
    if company_id is not None:
        q = q.filter(Contract.party_b_id == company_id)
    # ── H2 数据隔离（v1.3.0 多公司）：admin 看全部；
    # rep/operator 强制按绑定的公司 org_ids 过滤（主席可管多家公司）──
    if user.role == "admin":
        pass  # admin 全量
    else:
        org_ids = user.company_org_ids  # rep: 单 org；operator: 多 org
        if org_ids:
            my_companies = [r[0] for r in db.query(Company.id).filter(
                Company.org_id.in_(org_ids)).all()]
            if my_companies:
                q = q.filter(Contract.party_b_id.in_(my_companies))
            else:
                q = q.filter(Contract.id == -1)  # 绑定失效 → 看不到任何合同
        else:
            q = q.filter(Contract.id == -1)  # 无绑定公司 → 看不到任何合同（隔离原则）
    total = q.count()
    q = q.order_by(Contract.created_at.desc())

    paginated = False
    cur_page = 1
    eff_page_size = page_size
    if limit is not None:
        q = q.offset(offset).limit(limit)
        paginated = True
        cur_page = offset // limit + 1 if limit > 0 else 1
        eff_page_size = limit
    elif page is not None:
        q = q.offset((page - 1) * page_size).limit(page_size)
        paginated = True
        cur_page = page

    rows = q.all()
    ids = [c.id for c, _, _, _ in rows]
    items_by_contract: dict = {}
    if ids:
        for it in db.query(ContractItem).filter(ContractItem.contract_id.in_(ids)).order_by(ContractItem.sort_order).all():
            items_by_contract.setdefault(it.contract_id, []).append(it)

    result = []
    for contract, ct_name, region_name, company_name in rows:
        result.append(_serialize_contract(
            contract, ct_name, region_name, company_name,
            items_by_contract.get(contract.id, []),
        ))
    if paginated:
        return {"items": result, "total": total, "page": cur_page, "page_size": eff_page_size}
    return result


@router.get("/types/all")
def list_contract_types(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ContractType).order_by(ContractType.sort_order).all()


@router.get("/summarize/{region_id}")
def summarize_region(region_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """按区域汇总合同数据 — 供公式引擎使用"""
    contracts = db.query(Contract).filter(Contract.region_id == region_id).all()
    total_pop = total_talent = total_carbon = total_supply = 0.0
    sold_qty = total_amount = total_labor = total_supply_val = 0.0
    bonuses = []
    infra_pop_delta = 0.0
    infra_carbon_red = 0.0

    for c in contracts:
        for item in c.items:
            if c.contract_type_id == 4:  # 劳动力
                total_pop += item.quantity
                if (item.skill_level or 0) >= 0.5:
                    total_talent += item.quantity
                total_labor += (item.unit_price or 0) * item.quantity
            elif c.contract_type_id == 2:  # 开采
                total_carbon += item.quantity * (item.carbon_factor or 1.0)
                total_supply += item.quantity
            elif c.contract_type_id == 3:  # 采购
                total_supply_val += item.amount
            elif c.contract_type_id == 7:  # 销售
                sold_qty += item.quantity
                total_amount += item.amount
            elif c.contract_type_id == 1:  # 基建
                from ..models import InfraEmploymentBonus, InfrastructureType
                bonus = db.query(InfraEmploymentBonus).filter(
                    InfraEmploymentBonus.item_name == item.item_name
                ).first()
                if bonus:
                    bonuses.append({"name": item.item_name, "bonus": bonus.bonus * item.quantity})
                infra = db.query(InfrastructureType).filter(
                    InfrastructureType.name == item.item_name
                ).first()
                if infra and infra.carbon_reduction > 0:
                    infra_carbon_red += infra.carbon_reduction * item.quantity
                infra_pop_delta += (item.land_area or 0) * item.quantity * 0.1

    avg_price = total_amount / sold_qty if sold_qty > 0 else 0
    consumer_sat = min(1.0, total_supply / sold_qty) if sold_qty > 0 else 0

    return {
        "total_population": total_pop,
        "total_talent": total_talent,
        "total_carbon": total_carbon,
        "total_supply": total_supply,
        "sold_quantity": sold_qty,
        "avg_unit_price": avg_price,
        "total_labor_salary": total_labor,
        "consumer_satisfaction": consumer_sat,
        "infra_bonuses": bonuses,
        "infra_population_delta": infra_pop_delta,
        "infra_carbon_reduction": infra_carbon_red,
    }


# 注意：/{contract_id} 及其子路由必须注册在 /types/all、/summarize/... 之后，
# 保证「types / summarize」等字面量路径优先匹配（FastAPI 按注册顺序匹配同段数路由）。
@router.get("/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """合同详情（H2 修复：非 admin/operator 仅可看本公司合同）"""
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c:
        raise HTTPException(404, "合同不存在")
    _assert_contract_access(db, user, c)
    return _contract_row(db, c)


def _assert_contract_access(db: Session, user: User, c: Contract):
    """v1.3.1 审核加固：合同公司归属校验（admin 全量；rep/operator 限绑定公司）。
    供 get/update/approve/list_versions/batch/delete 共用，消除四处重复隔离逻辑。"""
    if user.role == "admin":
        return
    org_ids = user.company_org_ids
    if not org_ids:
        raise HTTPException(403, "无权访问该合同")
    my_companies = [r[0] for r in db.query(Company.id).filter(
        Company.org_id.in_(org_ids)).all()]
    if not my_companies or c.party_b_id not in my_companies:
        raise HTTPException(403, "无权访问其他公司的合同")


@router.post("")
def create_contract(data: ContractCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """创建合同（H1 修复：限 admin/operator——rep 只读，前端已隐藏入口，此处纵深防御）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权创建合同（仅管理员/运营可创建）")
    # 并发安全修复（三端口并发实测发现）：contract_no 生成曾用 count()+1（非原子），
    # 并发创建会生成相同编号 → unique 冲突 500。改为：顺序号 + 随机后缀保证唯一
    # （顺序号可读，随机后缀抗并发），冲突重试兜底。
    import random
    from sqlalchemy.exc import IntegrityError
    from ..database import commit_with_retry as _cwr
    for attempt in range(6):
        try:
            year = datetime.utcnow().year
            prefix = "CT"
            max_seq = db.query(Contract).filter(Contract.contract_no.like(f"{prefix}-{year}-%")).count()
            seq = max_seq + 1
            if attempt == 0:
                contract_no = f"{prefix}-{year}-{seq:04d}"
            else:
                # 冲突重试：追加随机后缀彻底避免同号（count 在并发下不随重试变化）
                contract_no = f"{prefix}-{year}-{seq:04d}-{random.randint(1000, 9999)}"

            # v1.3.1 金融化：创建即生效（active），无审批流；金额=合同金额或明细投资总额
            total_cost, expected_income = _compute_amounts(data.contract_type_id, data.items)
            if data.contract_amount is not None:
                total_cost = data.contract_amount
            contract = Contract(
                contract_no=contract_no,
                contract_name=data.contract_name,
                contract_type_id=data.contract_type_id,
                party_a=data.party_a,
                party_b_name=data.party_b_name,
                party_b_id=data.party_b_id,
                region_id=data.region_id,
                sign_date=data.sign_date,
                status="active",
                approval_status="none",
                notes=data.notes,
                total_cost=total_cost,
                expected_income=expected_income,
                contract_amount=data.contract_amount if data.contract_amount is not None else total_cost,
                contract_period=data.contract_period or "",
                owner=data.owner or "",
                attachment=data.attachment or "",
                created_by=user.username,
                updated_by=user.username,
            )
            db.add(contract)
            db.flush()

            for idx, item in enumerate(data.items):
                db.add(ContractItem(
                    contract_id=contract.id,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    land_area=item.land_area,
                    tax_rate=item.tax_rate,
                    skill_level=item.skill_level,
                    carbon_factor=item.carbon_factor,
                    total_cost=item.total_cost,
                    expected_income=item.expected_income,
                    investment_type=item.investment_type or "项目投资",
                    equity_ratio=item.equity_ratio or 0,
                    expected_return_rate=item.expected_return_rate or 0,
                    investment_period=item.investment_period or "",
                    sort_order=idx,
                ))

            # 版本留痕 v1 + 审计
            _save_version_snapshot(db, contract.id, _contract_row(db, contract), ["创建合同"], user.username)
            insert_audit_log(db, username=user.username, role=user.role, action="create", target="contract",
                             target_id=contract.id,
                             new_value=json.dumps({"contract_no": contract_no, "contract_name": data.contract_name}, ensure_ascii=False))

            # P1-3：WAL + busy_timeout 兜底，极端并发提交冲突时退避重试（2 次）
            _cwr(db)
            db.refresh(contract)
            return _contract_row(db, contract)
        except IntegrityError:
            # contract_no unique 冲突（并发竞态）：回滚重试换号
            db.rollback()
            continue
    raise HTTPException(409, "创建合同失败：编号冲突，请重试")


@router.put("/{contract_id}")
@router.patch("/{contract_id}")
def update_contract(contract_id: int, data: ContractUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """更新合同（PUT/PATCH 均可，字段部分更新）。
    H1 修复（2026-08-11 业务审核）：限 admin/operator——rep 只读，前端已隐藏入口，此处纵深防御。

    P0-1：补齐 ROUTE_MAP contract:update 指向的 PUT /api/contracts/{id}。
    与桌面端 CONTRACT_UPDATE 对齐：
      - 状态机强制（非法流转/未审批进执行一律 400）
      - 「状态更新 + 资金入账」同一事务（余额不足整体回滚，状态不落库）
      - 编辑留痕（contract_versions 旧快照）+ 审计日志
    """
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权编辑合同（仅管理员/运营可编辑）")
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c:
        raise HTTPException(404, "合同不存在")
    # v1.3.1 审核加固：operator 仅可编辑本公司合同
    _assert_contract_access(db, user, c)

    # ── v1.3.0 乐观锁：客户端传 expected_version 时校验版本（防并发编辑后写覆盖先写）──
    if data.expected_version is not None:
        if (c.version or 1) != data.expected_version:
            raise HTTPException(
                409,
                f"合同已被他人修改（当前版本 {c.version or 1}，您编辑的版本 {data.expected_version}），请刷新后重试")

    # 状态机强制（先校验、后写库）
    if data.status is not None and data.status != c.status:
        err = _validate_status_transition(c.status, data.status, c.approval_status)
        if err:
            raise HTTPException(400, err)

    operator = user.username
    old_row = _contract_row(db, c)
    changed = _changed_fields(old_row, data)
    # 编辑留痕：先保存旧快照，再执行更新（与桌面端一致）
    if changed:
        _save_version_snapshot(db, contract_id, old_row, changed, operator)

    # 字段更新（v1.3.1 金融化：审批字段弃用，新增金融字段可编辑）
    for f in ("contract_name", "contract_type_id", "party_a", "party_b_name", "party_b_id",
              "region_id", "sign_date", "status", "notes", "total_cost", "progress",
              "expected_income", "contract_amount", "contract_period", "owner", "attachment"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(c, f, v)
    c.updated_by = operator

    # 明细整体替换 + 重算合同级金额（未显式录入的明细金额按 数量×单价×(1+税率/100) 推算）
    if data.items is not None:
        # H2 修复（2026-08-11 业务审核）：前端编辑只传 7 个字段（不含 total_cost/expected_income），
        # 投资(5)/拨款(6) 等类型若按 1×0×税率 推算会归零 → 资金永不入账。
        # 从旧明细继承显式金额（对齐桌面端 contract.repo.ts:282-290）：
        # 新明细的 total_cost/expected_income 为空时，取同 item_name 旧明细的值。
        old_items = {
            (i.item_name or ""): i for i in db.query(ContractItem)
            .filter(ContractItem.contract_id == contract_id).all()
        }
        db.query(ContractItem).filter(ContractItem.contract_id == contract_id).delete(synchronize_session=False)
        merged_items = []
        for idx, item in enumerate(data.items):
            old = old_items.get(item.item_name or "")
            tc = item.total_cost
            ei = item.expected_income
            # 投资字段继承（v1.3.1 审核加固：旧版前端/部分字段更新不传时继承旧值，防清空）
            itype = item.investment_type
            eratio = item.equity_ratio
            erate = item.expected_return_rate
            iperiod = item.investment_period
            if (tc is None or tc <= 0) and old is not None and old.total_cost and old.total_cost > 0:
                tc = old.total_cost  # 继承旧明细显式金额（防推算归零）
            if (ei is None or ei <= 0) and old is not None and old.expected_income and old.expected_income > 0:
                ei = old.expected_income
            if not itype and old is not None and old.investment_type:
                itype = old.investment_type
            if eratio is None and old is not None and old.equity_ratio:
                eratio = old.equity_ratio
            if erate is None and old is not None and old.expected_return_rate:
                erate = old.expected_return_rate
            if not iperiod and old is not None and old.investment_period:
                iperiod = old.investment_period
            db.add(ContractItem(
                contract_id=contract_id,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                land_area=item.land_area,
                tax_rate=item.tax_rate,
                skill_level=item.skill_level,
                carbon_factor=item.carbon_factor,
                total_cost=tc,
                expected_income=ei,
                investment_type=itype,
                equity_ratio=eratio,
                expected_return_rate=erate,
                investment_period=iperiod,
                sort_order=idx,
            ))
            # 重算用继承后的明细（含 tc/ei + 投资字段继承值）——避免用原始 items 重算又归零
            merged_items.append(ItemData(
                item_name=item.item_name or "", quantity=item.quantity,
                unit_price=item.unit_price, land_area=item.land_area,
                tax_rate=item.tax_rate, skill_level=item.skill_level,
                carbon_factor=item.carbon_factor,
                total_cost=tc, expected_income=ei,
                investment_type=itype or "项目投资",
                equity_ratio=eratio or 0,
                expected_return_rate=erate or 0,
                investment_period=iperiod or "",
            ))
        tc, ei = _compute_amounts(c.contract_type_id or data.contract_type_id, merged_items)
        c.total_cost = tc
        c.expected_income = ei
    db.flush()

    # ── v1.3.1 金融化：审批自动入账已废弃（资金入账走资金模块手动操作）──

    # 审计日志
    insert_audit_log(db, username=operator, role=user.role, action="update", target="contract",
                     target_id=contract_id,
                     old_value=json.dumps({k: old_row.get(k) for k in
                                           set(changed) | {"contract_name", "status"} if k in old_row},
                                          ensure_ascii=False, default=str),
                     new_value=json.dumps({"contract_name": c.contract_name, "status": c.status,
                                           **{k: getattr(data, k, None) for k in changed if k != "items"}},
                                          ensure_ascii=False, default=str))

    # ── v1.3.0 乐观锁：版本自增（每次成功编辑 +1，客户端下次编辑需带新版本）──
    c.version = (c.version or 1) + 1

    commit_with_retry(db)
    db.refresh(c)
    return _contract_row(db, c)


@router.post("/{contract_id}/approve")
def approve_contract(contract_id: int, data: ApproveReq, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """合同审批状态机：submit / approve / reject（对齐桌面端 transitionApproval）。
    H1 修复（2026-08-11 业务审核）：审批操作限 admin/operator（rep 只读——前端已隐藏按钮，此处纵深防御）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权审批合同（仅管理员/运营可审批）")
    if data.action not in ("submit", "approve", "reject"):
        raise HTTPException(400, f"未知的审批操作：{data.action}（仅支持 submit / approve / reject）")
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c:
        raise HTTPException(404, "合同不存在")
    # v1.3.1 审核加固：operator 仅可审批本公司合同
    _assert_contract_access(db, user, c)

    operator = user.username
    before_row = _contract_row(db, c)

    if data.action == "submit":
        if c.approval_status not in ("none", "rejected"):
            raise HTTPException(400, "仅草稿或已驳回的合同可提交审批")
        c.approval_status = "pending"
        c.approved_by = operator
        c.approved_at = None
    elif data.action == "approve":
        if c.approval_status != "pending":
            raise HTTPException(400, "仅待审批的合同可批准")
        c.approval_status = "approved"
        c.approved_by = operator
        c.approved_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    elif data.action == "reject":
        if c.approval_status != "pending":
            raise HTTPException(400, "仅待审批的合同可驳回")
        c.approval_status = "rejected"
        c.approved_by = operator
        c.approved_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    c.updated_by = operator

    # 版本留痕 + 审计 + 通知
    _save_version_snapshot(db, contract_id, before_row,
                           ["提交审批" if data.action == "submit" else "审批通过" if data.action == "approve" else "审批驳回"],
                           operator)
    insert_audit_log(db, username=operator, role=user.role, action=data.action, target="contract",
                     target_id=contract_id,
                     old_value=json.dumps({"status": before_row.get("status"), "approval_status": before_row.get("approval_status")}, ensure_ascii=False),
                     new_value=json.dumps({"status": c.status, "approval_status": c.approval_status}, ensure_ascii=False))
    _notify_approval(db, c, data.action)

    commit_with_retry(db)
    db.refresh(c)
    return _contract_row(db, c)


@router.post("/batch-approve")
def batch_approve(data: BatchApproveReq, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """批量审批/删除：逐条独立 savepoint，单条失败不影响其他条；
    返回与桌面端一致的 {success, results, summary}。
    v1.3.1 审核加固：仅 admin/operator；逐条校验公司归属；delete 复用禁删保护。"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权批量操作合同（仅管理员/主席）")
    id_list = [n for n in data.ids if isinstance(n, int)]
    if not id_list:
        raise HTTPException(400, "未选择任何合同")
    if data.action not in ("submit", "approve", "delete"):
        raise HTTPException(400, f"无效的批量操作类型：{data.action}")

    operator = user.username
    results = []
    for cid in id_list:
        try:
            with db.begin_nested():
                c = db.query(Contract).filter(Contract.id == cid).first()
                if not c:
                    raise HTTPException(404, "合同不存在")
                # 审核加固：公司归属校验（admin 全量；operator 限绑定公司）
                _assert_contract_access(db, user, c)
                before_row = _contract_row(db, c)
                if data.action == "delete":
                    # 复用 delete_contract 的禁删保护（active/completed 禁删，防幂等误判）
                    if c.status in ("active", "completed"):
                        raise HTTPException(400, "已执行或已完成的合同不能删除，请使用「终止合同」")
                    # 同步清理关联流水（防 AUTOINCREMENT 重置后 id 复用命中旧流水）
                    db.query(AccountTransaction).filter(
                        AccountTransaction.contract_id == cid,
                        AccountTransaction.source_type == "contract",
                    ).delete(synchronize_session=False)
                    db.delete(c)
                    insert_audit_log(db, username=operator, role=user.role, action="delete", target="contract",
                                     target_id=cid,
                                     old_value=json.dumps({"contract_no": before_row.get("contract_no"),
                                                           "contract_name": before_row.get("contract_name"),
                                                           "status": before_row.get("status")}, ensure_ascii=False))
                    results.append({"id": cid, "success": True, "message": "删除成功"})
                    continue
                if data.action == "submit":
                    if c.approval_status not in ("none", "rejected"):
                        raise HTTPException(400, "仅草稿或已驳回的合同可提交审批")
                    c.approval_status = "pending"
                    c.approved_by = operator
                    c.approved_at = None
                    label = "提交审批"
                else:  # approve
                    if c.approval_status != "pending":
                        raise HTTPException(400, "仅待审批的合同可批准")
                    c.approval_status = "approved"
                    c.approved_by = operator
                    c.approved_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    label = "审批通过"
                c.updated_by = operator
                _save_version_snapshot(db, cid, before_row, [label], operator)
                insert_audit_log(db, username=operator, role=user.role, action=data.action, target="contract",
                                 target_id=cid,
                                 old_value=json.dumps({"status": before_row.get("status"),
                                                       "approval_status": before_row.get("approval_status")}, ensure_ascii=False),
                                 new_value=json.dumps({"status": c.status, "approval_status": c.approval_status}, ensure_ascii=False))
                _notify_approval(db, c, data.action)
                results.append({"id": cid, "success": True,
                                "message": "已提交审批" if data.action == "submit" else "审批通过"})
        except HTTPException as e:
            results.append({"id": cid, "success": False, "message": e.detail})
        except Exception as e:  # noqa: BLE001
            results.append({"id": cid, "success": False, "message": str(e) or "操作失败"})

    commit_with_retry(db)
    ok_count = sum(1 for r in results if r["success"])
    return {"success": True, "results": results,
            "summary": {"total": len(results), "ok": ok_count, "failed": len(results) - ok_count}}


@router.get("/{contract_id}/versions")
def list_versions(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """合同版本历史：按版本号升序返回快照（对齐桌面端 CONTRACT_LIST_VERSIONS）。
    v1.3.1 审核加固：公司归属校验（rep 不可读他司快照）。"""
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c:
        raise HTTPException(404, "合同不存在")
    _assert_contract_access(db, user, c)
    rows = db.query(ContractVersion).filter(ContractVersion.contract_id == contract_id) \
        .order_by(ContractVersion.version.asc()).all()
    result = []
    for r in rows:
        try:
            snapshot = json.loads(r.snapshot or "{}")
        except Exception:  # noqa: BLE001
            snapshot = {}
        try:
            changed = json.loads(r.changed_fields or "[]")
        except Exception:  # noqa: BLE001
            changed = []
        result.append({
            "id": r.id,
            "contract_id": contract_id,
            "version": r.version,
            "snapshot": snapshot,
            "changed_fields": changed,
            "created_by": r.created_by or "",
            "created_at": _fmt_dt(r.created_at) or "",
        })
    return result


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除合同（v1.3.1 审核加固：仅 admin/operator + 公司归属校验）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权删除合同（仅管理员/主席）")
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c:
        raise HTTPException(404, "合同不存在")
    # 审核加固：公司归属校验（operator 限绑定公司）
    _assert_contract_access(db, user, c)
    # 交付验收修复：已入账合同禁止删除（防 id 复用后流水误判幂等）
    if c.status in ("active", "completed"):
        raise HTTPException(400, "已执行或已完成的合同不能删除，请使用「终止合同」")
    old_row = _contract_row(db, c)
    # 同步清理关联流水（防 AUTOINCREMENT 重置后新合同复用 id 命中旧流水）
    db.query(AccountTransaction).filter(
        AccountTransaction.contract_id == contract_id,
        AccountTransaction.source_type == "contract",
    ).delete(synchronize_session=False)
    db.delete(c)
    insert_audit_log(db, username=user.username, role=user.role, action="delete", target="contract",
                     target_id=contract_id,
                     old_value=json.dumps({"contract_no": old_row.get("contract_no"),
                                           "contract_name": old_row.get("contract_name"),
                                           "status": old_row.get("status")}, ensure_ascii=False))
    # P1-3：写提交退避重试（WAL 下锁冲突已大幅减少，极端并发仍可能 locked）
    commit_with_retry(db)
    return {"success": True}
