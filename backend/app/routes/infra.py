"""基建计算 + 类型查询"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from ..database import get_db
from ..models import InfrastructureType, Contract, ContractItem, Region
from ..auth import get_current_user

router = APIRouter()


@router.get("/types")
def list_infra_types(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """列出所有基建类型"""
    types = db.query(InfrastructureType).order_by(InfrastructureType.name).all()
    return [{"id": t.id, "name": t.name, "category": t.category, "recommended_ratio": t.recommended_ratio, "carbon_reduction": t.carbon_reduction} for t in types]


@router.get("/calculate")
def infra_calculate(
    region_id: int = Query(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user)
):
    """基建计算 — 对比建议占比和当前占比"""
    types = db.query(InfrastructureType).order_by(InfrastructureType.recommended_ratio.desc()).all()
    region = db.query(Region).filter(Region.id == region_id).first()
    population = region.population if region else 0

    # 已建数量
    built = db.query(
        ContractItem.item_name,
        func.sum(ContractItem.quantity).label("total_qty"),
    ).join(Contract, Contract.id == ContractItem.contract_id)\
     .filter(Contract.region_id == region_id)\
     .group_by(ContractItem.item_name).all()

    qty_map = {b.item_name: b.total_qty for b in built}
    total_current = sum(qty_map.values())

    result = []
    for t in types:
        qty = qty_map.get(t.name, 0) or 0
        ratio = t.recommended_ratio
        current_ratio = qty / total_current if total_current > 0 else 0
        annual_revenue = t.revenue_index * population
        total_maint = t.maintenance_fee * qty
        activated_qty = qty if t.category == "产业配套" else 0
        annual_usage = t.activation_price * activated_qty
        actual_carbon_red = t.carbon_reduction * qty if t.category == "产业配套" else 0
        net_cost = total_maint + annual_usage - annual_revenue

        result.append({
            "name": t.name,
            "category": t.category,
            "land_area": t.default_land_area,
            "price": t.price,
            "revenue_index": t.revenue_index,
            "recommended_ratio": ratio,
            "maintenance_fee": t.maintenance_fee,
            "current_qty": qty,
            "current_ratio": current_ratio,
            "annual_revenue": annual_revenue,
            "total_maintenance": total_maint,
            "population_addition": t.population_addition,
            "talent_addition": t.talent_addition,
            "happiness_index": t.happiness_index,
            "h_bonus": t.h_bonus,
            "carbon_reduction": t.carbon_reduction,
            "activation_price": t.activation_price,
            "annual_usage_fee": annual_usage,
            "actual_carbon_reduction": actual_carbon_red,
            "net_operating_cost": net_cost,
        })

    total_carbon_reduction = sum(r["actual_carbon_reduction"] for r in result)

    return {
        "population": population,
        "baseline_carbon": population * 10,
        "total_current": total_current,
        "total_revenue": sum(r["annual_revenue"] for r in result),
        "total_maintenance": sum(r["total_maintenance"] for r in result),
        "total_carbon_reduction": total_carbon_reduction,
        "effective_carbon_reduction": total_carbon_reduction,
        "total_usage_fee": sum(r["annual_usage_fee"] for r in result),
        "items": result,
    }
