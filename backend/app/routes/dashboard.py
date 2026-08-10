"""仪表盘 + 基建类型"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Region, Contract, Company, ContractItem, InfrastructureType
from ..auth import get_current_user

router = APIRouter()


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    total_regions = db.query(Region).count()
    total_contracts = db.query(Contract).count()
    total_companies = db.query(Company).filter(Company.is_active == 1).count()
    total_land = db.query(ContractItem).all()
    total_land_area = sum((item.quantity * item.land_area) for item in total_land)
    avg_happiness = db.query(Region).filter(Region.current_happiness.isnot(None)).all()
    avg_employment = db.query(Region).filter(Region.current_employment_rate.isnot(None)).all()

    # P1-1 扩展：合同状态分布 + 待审批计数 + 最近 6 条合同，
    # 渲染端 Dashboard 不再拉 CONTRACT_LIST 全表，避免云库增长后每次拖全量。
    status_counts = {}
    for status, cnt in db.query(Contract.status, func.count(Contract.id)).group_by(Contract.status).all():
        status_counts[status or "draft"] = cnt
    approval_pending = (
        db.query(Contract).filter(Contract.approval_status == "pending").count()
    )
    recent_contracts = [
        {
            "id": c.id,
            "contract_no": c.contract_no,
            "contract_name": c.contract_name,
            "status": c.status,
            "created_at": c.created_at.isoformat(sep=" ") if c.created_at else None,
        }
        for c in db.query(Contract).order_by(Contract.created_at.desc()).limit(6).all()
    ]

    return {
        "total_regions": total_regions,
        "total_contracts": total_contracts,
        "total_companies": total_companies,
        "total_land_area": round(total_land_area, 2),
        "avg_happiness": round(sum(r.current_happiness for r in avg_happiness) / max(len(avg_happiness), 1), 2),
        "avg_employment": round(sum(r.current_employment_rate for r in avg_employment) / max(len(avg_employment), 1), 2),
        "contract_status_counts": status_counts,
        "contract_approval_pending": approval_pending,
        "recent_contracts": recent_contracts,
    }


@router.get("/infrastructure-types")
def list_infra_types(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(InfrastructureType).order_by(InfrastructureType.name).all()


@router.get("/regions-summary")
def all_regions_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """所有区域的汇总对比"""
    regions = db.query(Region).order_by(Region.name).all()
    result = []
    for r in regions:
        result.append({
            "id": r.id,
            "name": r.name,
            "population": r.population,
            "talent_population": r.talent_population,
            "carbon_emissions": r.carbon_emissions,
            "current_happiness": r.current_happiness,
            "current_employment_rate": r.current_employment_rate,
        })
    return result
