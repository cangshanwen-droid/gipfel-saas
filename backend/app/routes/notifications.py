"""通知中心（P0-1 补齐：notification:list / unread-count / mark-read）"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Notification, User

router = APIRouter()


@router.get("")
def list_notifications(limit: int = 50, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """当前用户通知列表（最新在前，默认 50 条）。"""
    limit = max(1, min(limit, 200))
    rows = db.query(Notification).filter(Notification.user_id == user.id) \
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    items = []
    for n in rows:
        items.append(_serialize(n))
    return {"success": True, "items": items}


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.query(Notification).filter(Notification.user_id == user.id, Notification.read == 0).count()
    return {"success": True, "count": count}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read == 0) \
        .update({"read": 1}, synchronize_session=False)
    db.commit()
    return {"success": True}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(404, "通知不存在")
    if n.user_id != user.id:
        raise HTTPException(403, "无权操作他人通知")
    n.read = 1
    db.commit()
    return {"success": True}


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "title": n.title,
        "content": n.content,
        "type": n.type,
        "link": n.link,
        "read": n.read,
        "created_at": n.created_at.isoformat(sep=" ") if isinstance(n.created_at, datetime) else n.created_at,
    }
