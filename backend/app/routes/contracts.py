"""合同 CRUD + 区域汇总"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from ..database import get_db, commit_with_retry
from ..models import Contract, ContractItem, ContractType, Region, Company
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
def list_contracts(
    region_id: Optional[int] = Query(None),
    # P1-1 分页：两种风格都支持——
    #   limit/offset（cloudApi contract:list 默认 limit=200）
    #   page/page_size（REST 风格，审计建议）
    # 传了任一参数即返回 {items, total, page, page_size}，否则返回裸数组（兼容旧调用方）。
    limit: Optional[int] = Query(None, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    page: Optional[int] = Query(None, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """合同列表 — LEFT JOIN 返回 contract_type_name/region_name/company_name，与桌面端 contract.repo.ts 一致"""
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
    result = []
    for contract, ct_name, region_name, company_name in rows:
        item = {col.name: getattr(contract, col.name) for col in Contract.__table__.columns}
        item["contract_type_name"] = ct_name
        item["region_name"] = region_name
        item["company_name"] = company_name
        # DateTime → ISO 字符串（与桌面端本地 SQLite 的 'YYYY-MM-DD HH:MM:SS' 文本对齐）
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat(sep=" ")
        if isinstance(item.get("updated_at"), datetime):
            item["updated_at"] = item["updated_at"].isoformat(sep=" ")
        result.append(item)
    if paginated:
        return {"items": result, "total": total, "page": cur_page, "page_size": eff_page_size}
    return result


@router.get("/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c: raise HTTPException(404, "合同不存在")
    result = {col.name: getattr(c, col.name) for col in Contract.__table__.columns}
    result["contract_type_name"] = c.contract_type.name if c.contract_type else None
    result["region_name"] = c.region.name if c.region else None
    result["company_name"] = c.party_b.name if c.party_b else None
    return result


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

    # P1-3：WAL + busy_timeout 兜底，极端并发提交冲突时退避重试（2 次）
    commit_with_retry(db)
    db.refresh(contract)
    return contract


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == contract_id).first()
    if not c: raise HTTPException(404, "合同不存在")
    db.delete(c)
    # P1-3：写提交退避重试（WAL 下锁冲突已大幅减少，极端并发仍可能 locked）
    commit_with_retry(db)
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
