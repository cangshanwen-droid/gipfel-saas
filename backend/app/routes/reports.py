"""占地面积报表"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Contract, ContractItem, Region
from ..auth import get_current_user

router = APIRouter()


@router.get("/land-area")
def land_area_report(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """按区域+项目名汇总占地面积"""
    results = db.query(
        Region.name.label("region_name"),
        ContractItem.item_name,
        func.sum(ContractItem.quantity).label("total_quantity"),
        func.sum(ContractItem.quantity * ContractItem.land_area).label("total_land_area"),
    ).join(Contract, Contract.id == ContractItem.contract_id)\
     .join(Region, Region.id == Contract.region_id)\
     .filter(ContractItem.land_area > 0)\
     .group_by(Region.name, ContractItem.item_name)\
     .order_by(Region.name, func.sum(ContractItem.quantity * ContractItem.land_area).desc())\
     .all()

    return [
        {"region_name": r.region_name, "item_name": r.item_name,
         "total_quantity": r.total_quantity, "total_land_area": r.total_land_area}
        for r in results
    ]


@router.get("/land-area-by-region")
def land_area_by_region(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """按区域汇总"""
    results = db.query(
        Region.name.label("region_name"),
        func.count(func.distinct(Contract.id)).label("contract_count"),
        func.sum(ContractItem.quantity).label("total_items"),
        func.sum(ContractItem.quantity * ContractItem.land_area).label("total_land_area"),
    ).join(Contract, Contract.id == ContractItem.contract_id)\
     .join(Region, Region.id == Contract.region_id)\
     .filter(ContractItem.land_area > 0)\
     .group_by(Region.name)\
     .order_by(func.sum(ContractItem.quantity * ContractItem.land_area).desc())\
     .all()

    return [
        {"region_name": r.region_name, "contract_count": r.contract_count,
         "total_items": r.total_items, "total_land_area": r.total_land_area}
        for r in results
    ]
