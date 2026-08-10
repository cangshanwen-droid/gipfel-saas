"""审计日志（P0-1 补齐：audit:list / audit:log）"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_admin_user
from ..database import get_db
from ..models import AuditLog, User

router = APIRouter()


class AuditLogCreate(BaseModel):
    username: str = ""
    role: str = ""
    action: str
    target: str = ""
    target_id: Optional[int] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    ip: Optional[str] = None
    result: str = "success"


@router.get("")
def list_audit_logs(username: Optional[str] = None, action: Optional[str] = None,
                    page: int = 1, page_size: int = 50,
                    db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    """审计日志列表（分页，对齐桌面端 listAuditLogs）。"""
    q = db.query(AuditLog)
    if username:
        q = q.filter(AuditLog.username == username)
    if action:
        q = q.filter(AuditLog.action == action)
    total = q.count()
    page = max(page, 1)
    page_size = max(1, min(page_size, 200))
    rows = q.order_by(AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "username": r.username,
            "role": r.role,
            "action": r.action,
            "target": r.target,
            "target_id": r.target_id,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "ip": r.ip,
            "timestamp": r.timestamp.isoformat(sep=" ") if isinstance(r.timestamp, datetime) else r.timestamp,
            "result": r.result,
        })
    return {"success": True, "items": items, "total": total}


@router.post("/log")
def write_audit_log(data: AuditLogCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """写入审计日志（业务内部调用；操作者以登录用户兜底）。"""
    db.add(AuditLog(
        username=data.username or user.username,
        role=data.role or user.role,
        action=data.action,
        target=data.target,
        target_id=data.target_id,
        old_value=data.old_value,
        new_value=data.new_value,
        ip=data.ip,
        result=data.result,
    ))
    db.commit()
    return {"success": True}
