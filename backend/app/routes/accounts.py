"""财务账户管理"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import RegionAccount, AccountTransaction, Region
from ..auth import get_current_user

router = APIRouter()


class TransactionCreate(BaseModel):
    account_id: int
    trans_type: str  # income / expense
    category: str = ""
    amount: float
    description: str = ""
    fiscal_year: Optional[int] = None


@router.get("")
def list_accounts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(RegionAccount).order_by(RegionAccount.is_master.desc(), RegionAccount.region_id).all()


@router.get("/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    a = db.query(RegionAccount).filter(RegionAccount.id == account_id).first()
    if not a: raise HTTPException(404, "账户不存在")
    return a


@router.get("/{account_id}/transactions")
def list_transactions(account_id: int, fiscal_year: Optional[int] = None,
                       db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(AccountTransaction).filter(AccountTransaction.account_id == account_id)
    if fiscal_year: q = q.filter(AccountTransaction.fiscal_year == fiscal_year)
    return q.order_by(AccountTransaction.created_at.desc()).all()


@router.post("/transactions")
def add_transaction(data: TransactionCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    txn = AccountTransaction(**data.model_dump())
    db.add(txn)

    sign = 1 if data.trans_type == "income" else -1
    account = db.query(RegionAccount).filter(RegionAccount.id == data.account_id).first()
    if account:
        account.balance += sign * data.amount

    db.commit()
    return {"success": True}


@router.get("/summary/all")
def accounts_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    accounts = db.query(RegionAccount).order_by(RegionAccount.is_master.desc(), RegionAccount.region_id).all()
    total_balance = sum(a.balance or 0 for a in accounts)
    region_count = sum(1 for a in accounts if not a.is_master)
    return {"accounts": accounts, "total_balance": total_balance, "region_count": region_count}
