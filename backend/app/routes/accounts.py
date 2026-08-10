"""财务账户管理

P0-1 修复：补齐 ROUTE_MAP 指向的缺失路由：
  - POST /api/accounts            （account:create，创建区域账户）
  - GET  /api/accounts/years      （account:years，流水年度下拉）
  - POST /api/accounts/transactions（account:add-transaction，入账+余额更新原子）
  - GET  /api/accounts/summary/all（account:summary）
"""
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db, commit_with_retry
from ..models import AccountTransaction, Region, RegionAccount, User
from ..services.audit import insert_audit_log
from ..services.notify import notify_account_managers

router = APIRouter()


class AccountCreate(BaseModel):
    region_id: int
    account_name: str
    is_master: int = 0
    initial_balance: float = 0


class TransactionCreate(BaseModel):
    account_id: int
    trans_type: str  # income / expense
    category: str = ""
    amount: float
    description: str = ""
    fiscal_year: Optional[int] = None
    operator: Optional[str] = None  # 兼容透传，实际以登录用户为准
    contract_id: Optional[int] = None
    source_type: str = "manual"


@router.get("")
def list_accounts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    accounts = db.query(RegionAccount).order_by(RegionAccount.is_master.desc(), RegionAccount.region_id).all()
    return _with_region_name(db, accounts)


@router.get("/summary/all")
def accounts_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    accounts = db.query(RegionAccount).order_by(RegionAccount.is_master.desc(), RegionAccount.region_id).all()
    rows = _with_region_name(db, accounts)
    total_balance = sum((a.balance or 0) for a in rows)
    region_count = sum(1 for a in rows if not a.is_master)
    return {"accounts": rows, "total_balance": total_balance, "region_count": region_count}


@router.get("/years")
def account_years(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """全部流水年度（年度筛选下拉动态化），与桌面端 ACCOUNT_YEARS 一致。"""
    rows = db.query(AccountTransaction.fiscal_year).filter(
        AccountTransaction.fiscal_year.isnot(None)
    ).distinct().order_by(AccountTransaction.fiscal_year.desc()).all()
    return [r[0] for r in rows]


@router.post("")
def create_account(data: AccountCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """创建区域账户（对齐桌面端 ACCOUNT_CREATE：初始余额不允许为负）。"""
    if not db.query(Region.id).filter(Region.id == data.region_id).first():
        raise HTTPException(400, "区域不存在")
    initial_balance = float(data.initial_balance or 0)
    if initial_balance < 0:
        raise HTTPException(400, "初始余额必须为不小于 0 的数字")
    acct = RegionAccount(
        region_id=data.region_id,
        account_name=data.account_name,
        is_master=data.is_master or 0,
        balance=initial_balance,
    )
    db.add(acct)
    db.flush()
    insert_audit_log(db, username=user.username, role=user.role, action="create", target="account",
                     target_id=acct.id,
                     new_value=f'{{"account_name": "{data.account_name}", "region_id": {data.region_id}}}')
    commit_with_retry(db)
    db.refresh(acct)
    return {"success": True, "id": acct.id}


@router.get("/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    a = db.query(RegionAccount).filter(RegionAccount.id == account_id).first()
    if not a:
        raise HTTPException(404, "账户不存在")
    return _with_region_name(db, [a])[0]


@router.get("/{account_id}/transactions")
def list_transactions(account_id: int, fiscal_year: Optional[int] = None,
                      db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(AccountTransaction).filter(AccountTransaction.account_id == account_id)
    if fiscal_year:
        q = q.filter(AccountTransaction.fiscal_year == fiscal_year)
    return _serialize_txns(q.order_by(AccountTransaction.created_at.desc()).all())


@router.post("/transactions")
def add_transaction(data: TransactionCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """入账 + 余额更新（同一事务）；支出余额不足 → 400，不允许负余额。
    对齐桌面端 ACCOUNT_ADD_TRANSACTION 的校验与原子性。"""
    if data.trans_type not in ("income", "expense"):
        raise HTTPException(400, f"非法交易类型：{data.trans_type}（仅支持 income / expense）")
    amount = float(data.amount)
    if not (amount > 0):
        raise HTTPException(400, "交易金额必须为大于 0 的数字")
    if amount > 100000000:
        raise HTTPException(400, "交易金额不能超过 100000000")

    account = db.query(RegionAccount).filter(RegionAccount.id == data.account_id).first()
    if not account:
        raise HTTPException(404, "账户不存在")
    if data.trans_type == "expense" and (account.balance or 0) < amount:
        raise HTTPException(400, f"余额不足：账户余额 {(account.balance or 0):.2f}")

    txn = AccountTransaction(
        account_id=data.account_id,
        trans_type=data.trans_type,
        category=data.category,
        amount=amount,
        description=data.description,
        fiscal_year=data.fiscal_year,
        operator=user.username,
        contract_id=data.contract_id,
        source_type=data.source_type or "manual",
    )
    db.add(txn)
    sign = 1 if data.trans_type == "income" else -1
    account.balance = round((account.balance or 0) + sign * amount, 2)

    insert_audit_log(db, username=user.username, role=user.role,
                     action="income" if data.trans_type == "income" else "expense",
                     target="transaction", target_id=data.account_id,
                     new_value=f'{{"trans_type": "{data.trans_type}", "amount": {amount}, "category": "{data.category}", "description": "{data.description}", "contract_id": {data.contract_id}}}')
    try:
        region_name = db.query(Region.name).filter(Region.id == account.region_id).scalar() or ""
        sign_str = "+" if data.trans_type == "income" else "-"
        notify_account_managers(
            db,
            f"{region_name + '·' if region_name else ''}账户{'收入' if data.trans_type == 'income' else '支出'} {sign_str}¥{amount:.2f}",
            f"{data.category or '交易'}：{data.description or '账户资金变动'}",
            "transaction", "/accounts",
        )
    except Exception:  # noqa: BLE001
        pass

    commit_with_retry(db)
    return {"success": True}


def _with_region_name(db: Session, accounts):
    result = []
    for a in accounts:
        row = {col.name: getattr(a, col.name) for col in RegionAccount.__table__.columns}
        row["region_name"] = db.query(Region.name).filter(Region.id == a.region_id).scalar() if a.region_id else None
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].isoformat(sep=" ")
        if isinstance(row.get("updated_at"), datetime):
            row["updated_at"] = row["updated_at"].isoformat(sep=" ")
        result.append(row)
    return result


def _serialize_txns(rows):
    result = []
    for t in rows:
        row = {col.name: getattr(t, col.name) for col in AccountTransaction.__table__.columns}
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].isoformat(sep=" ")
        result.append(row)
    return result
