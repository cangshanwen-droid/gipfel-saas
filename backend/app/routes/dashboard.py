"""仪表盘 + 基建类型"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Region, Contract, Company, ContractItem, InfrastructureType, RegionAccount, User, AuditLog
from ..auth import get_current_user, get_admin_user

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

    # 与桌面端 DashboardSummary 类型对齐
    total_contract_amount = db.query(func.coalesce(func.sum(Contract.total_cost), 0)).scalar() or 0
    total_account_balance = db.query(func.coalesce(func.sum(RegionAccount.balance), 0)).scalar() or 0
    total_accounts = db.query(RegionAccount).count()

    return {
        "total_regions": total_regions,
        "total_contracts": total_contracts,
        "total_companies": total_companies,
        "total_land_area": round(total_land_area, 2),
        "avg_happiness": round(sum(r.current_happiness for r in avg_happiness) / max(len(avg_happiness), 1), 2),
        "avg_employment": round(sum(r.current_employment_rate for r in avg_employment) / max(len(avg_employment), 1), 2),
        "total_contract_amount": round(total_contract_amount, 2),
        "total_account_balance": round(total_account_balance, 2),
        "total_accounts": total_accounts,
        "contract_status_counts": status_counts,
        "contract_approval_pending": approval_pending,
        "recent_contracts": recent_contracts,
    }


@router.get("/system-stats")
def system_stats(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    """系统概览（仅 admin）：用户构成 + 活跃度 + 最近创建用户（对齐桌面端 getSystemStats）。"""
    now = datetime.utcnow()
    recent_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    recent_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    total_users = db.query(User).count()
    admin_count = db.query(User).filter(User.role == "admin").count()
    operator_count = db.query(User).filter(User.role == "operator").count()
    rep_count = db.query(User).filter(User.role == "rep").count()
    active_users_30d = db.query(User).filter(
        User.last_login.isnot(None), User.last_login >= recent_30d
    ).count()
    logins_24h = db.query(AuditLog).filter(
        AuditLog.action == "login", AuditLog.result == "success",
        AuditLog.timestamp >= recent_24h,
    ).count()

    recent_users = []
    for u in db.query(User).order_by(User.created_at.desc()).limit(6).all():
        recent_users.append({
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at.isoformat(sep=" ") if u.created_at else None,
            "last_login": u.last_login,
        })

    return {"success": True, "stats": {
        "total_users": total_users,
        "admin_count": admin_count,
        "operator_count": operator_count,
        "rep_count": rep_count,
        "active_users_30d": active_users_30d,
        "logins_24h": logins_24h,
        "recent_users": recent_users,
    }}


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
