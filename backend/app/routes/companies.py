"""公司 CRUD"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Company
from ..auth import get_current_user

router = APIRouter()

class CompanyCreate(BaseModel):
    name: str
    region: str = ""
    company_type: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    company_type: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[int] = None

@router.get("")
def list_companies(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Company).filter(Company.is_active == 1).order_by(Company.name).all()

@router.get("/{company_id}")
def get_company(company_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c: raise HTTPException(404, "公司不存在")
    return c

@router.post("")
def create_company(data: CompanyCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = Company(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

@router.put("/{company_id}")
def update_company(company_id: int, data: CompanyUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c: raise HTTPException(404, "公司不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return c

@router.delete("/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c: raise HTTPException(404, "公司不存在")
    c.is_active = 0
    db.commit()
    return {"success": True}
