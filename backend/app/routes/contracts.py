"""合同 CRUD + 区域汇总"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from ..database import get_db
from ..models import Contract, ContractItem, ContractType, Region
from ..auth import get_current_user

router = APIRouter()


class ItemData(BaseModel):
    item_name: str
    quantity: float = 1
    unit_price: float = 0
    land_area: float = 0
    tax_rate: float = 0
    skill_level: float = 0
    carbon_factor: float = 0

class ContractCreate(BaseModel):
    contract_name: str
    contract_type_id: Optional[int] = None
    party_a: str = ""
    party_b_name: str = ""
    party_b_id: Optional[int] = None
    region_id: Optional[int] = None
    sign_date: Optional[str] = None
    status: str = "active"
    notes: str = ""
    items: List[ItemData] = []


@router.get("")
def list_contracts(region_id: Optional[int] = Query(None), db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Contract)
    if region_id:
        q = q.filter(Contract.region_id == region_id)
    return q.order_by(Contract.created_at.desc()).all()


@router.get("/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c: raise HTTPException(404, "合同不存在")
    return c


@router.post("")
def create_contract(data: ContractCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    year = datetime.utcnow().year
    prefix = "CT"
    max_seq = db.query(Contract).filter(Contract.contract_no.like(f"{prefix}-{year}-%")).count()
    contract_no = f"{prefix}-{year}-{max_seq + 1:04d}"

    contract = Contract(
        contract_no=contract_no,
        contract_name=data.contract_name,
        contract_type_id=data.contract_type_id,
        party_a=data.party_a,
        party_b_name=data.party_b_name,
        party_b_id=data.party_b_id,
        region_id=data.region_id,
        sign_date=data.sign_date,
        status=data.status,
        notes=data.notes,
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
            sort_order=idx,
        ))

    db.commit()
    db.refresh(contract)
    return contract


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c: raise HTTPException(404, "合同不存在")
    db.delete(c)
    db.commit()
    return {"success": True}


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
