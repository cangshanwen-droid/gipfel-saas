"""审计日志写入（对齐桌面端 audit.repo.insertAuditLog）"""
from ..models import AuditLog


def insert_audit_log(
    db,
    username: str = "",
    role: str = "",
    action: str = "",
    target: str = "",
    target_id=None,
    old_value=None,
    new_value=None,
    ip=None,
    result: str = "success",
):
    """写入一条审计日志（挂到当前 session，由调用方 commit）。"""
    db.add(AuditLog(
        username=username, role=role, action=action, target=target,
        target_id=target_id, old_value=old_value, new_value=new_value,
        ip=ip, result=result,
    ))
