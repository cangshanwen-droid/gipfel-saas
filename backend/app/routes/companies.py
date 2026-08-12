"""公司 CRUD"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Company, Organization, User
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
def create_company(data: CompanyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin/operator 可创建公司（rep 只读）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权创建公司（仅管理员/主席）")
    c = Company(**data.model_dump())
    db.add(c)
    db.flush()
    # 公司→组织 1:1 同步（用户绑定 org_id 指向 organizations，须与公司实时对应；
    # 组织独立于公司表，公司 id 与组织 id 通过同名映射关联）
    existing_org = db.query(Organization).filter(Organization.name == c.name).first()
    if existing_org:
        c.org_id = existing_org.id
    else:
        org = Organization(name=c.name)
        db.add(org)
        db.flush()
        c.org_id = org.id
    db.commit()
    db.refresh(c)
    return c

@router.put("/{company_id}")
def update_company(company_id: int, data: CompanyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin/operator 可改公司（rep 只读）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权修改公司（仅管理员/主席）")
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c: raise HTTPException(404, "公司不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return c

@router.delete("/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin 可停用公司"""
    if user.role != "admin":
        raise HTTPException(403, "无权停用公司（仅管理员）")
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c: raise HTTPException(404, "公司不存在")
    c.is_active = 0
    db.commit()
    return {"success": True}
