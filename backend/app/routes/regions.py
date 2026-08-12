"""区域 CRUD"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Region, User
from ..auth import get_current_user

router = APIRouter()


class RegionCreate(BaseModel):
    name: str
    population: float = 0
    talent_population: float = 0
    carbon_emissions: float = 0
    population_capacity: float = 10000
    base_growth_rate: float = 0.03

class RegionUpdate(BaseModel):
    name: Optional[str] = None
    population: Optional[float] = None
    talent_population: Optional[float] = None
    carbon_emissions: Optional[float] = None
    population_capacity: Optional[float] = None
    base_growth_rate: Optional[float] = None


@router.get("")
def list_regions(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Region).order_by(Region.name).all()

@router.get("/{region_id}")
def get_region(region_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    r = db.query(Region).filter(Region.id == region_id).first()
    if not r: raise HTTPException(404, "区域不存在")
    return r

@router.post("")
def create_region(data: RegionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin/operator 可创建区域（rep 只读）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权创建区域（仅管理员/主席）")
    r = Region(**data.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r

@router.put("/{region_id}")
def update_region(region_id: int, data: RegionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin/operator 可改区域（rep 只读）"""
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "无权修改区域（仅管理员/主席）")
    r = db.query(Region).filter(Region.id == region_id).first()
    if not r: raise HTTPException(404, "区域不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    return r

@router.delete("/{region_id}")
def delete_region(region_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v1.3.1 审核加固：仅 admin 可删区域（rep/operator 只读）"""
    if user.role != "admin":
        raise HTTPException(403, "无权删除区域（仅管理员）")
    r = db.query(Region).filter(Region.id == region_id).first()
    if not r: raise HTTPException(404, "区域不存在")
    db.delete(r)
    db.commit()
    return {"success": True}
