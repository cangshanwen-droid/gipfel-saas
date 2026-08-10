"""公告（P0-1 补齐：announcement:list / active-list / create / delete）"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db, commit_with_retry
from ..models import Announcement, Region, User
from ..services.notify import notify_all

router = APIRouter()


class AnnouncementCreate(BaseModel):
    title: str
    content: str
    region_id: Optional[int] = None
    priority: str = "normal"
    created_by: str = ""


@router.get("")
def list_announcements(priority: Optional[str] = None, region_id: Optional[int] = None,
                       db: Session = Depends(get_db), _=Depends(get_current_user)):
    """管理端公告列表（对齐桌面端 ANNOUNCEMENT_LIST：仅 active，可按优先级/区域筛选）。"""
    q = db.query(Announcement).filter(Announcement.is_active == 1)
    if priority:
        q = q.filter(Announcement.priority == priority)
    if region_id is not None:
        q = q.filter((Announcement.region_id.is_(None)) | (Announcement.region_id == region_id))
    rows = q.order_by(
        Announcement.priority.desc(), Announcement.created_at.desc()
    ).all()
    return [_serialize(db, a) for a in rows]


@router.get("/active")
def active_announcements(region_id: Optional[int] = None,
                         db: Session = Depends(get_db), _=Depends(get_current_user)):
    """首页活跃公告（对齐桌面端 ANNOUNCEMENT_ACTIVE_LIST：最新 10 条）。"""
    q = db.query(Announcement).filter(Announcement.is_active == 1)
    if region_id is not None:
        q = q.filter((Announcement.region_id.is_(None)) | (Announcement.region_id == region_id))
    rows = q.order_by(Announcement.created_at.desc()).limit(10).all()
    return [_serialize(db, a) for a in rows]


@router.post("")
def create_announcement(data: AnnouncementCreate, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    if not data.title.strip():
        raise HTTPException(400, "公告标题不能为空")
    if data.region_id is not None and not db.query(Region.id).filter(Region.id == data.region_id).first():
        raise HTTPException(400, "区域不存在")
    a = Announcement(
        title=data.title,
        content=data.content,
        region_id=data.region_id,
        priority=data.priority if data.priority in ("high", "normal", "low") else "normal",
        created_by=data.created_by or user.username,
    )
    db.add(a)
    db.flush()
    try:
        notify_all(db, f"新公告{'（紧急）' if a.priority == 'high' else ''}：{a.title}",
                   (a.content or "")[:60] or "点击查看公告详情", "announcement", "/announcements")
    except Exception:  # noqa: BLE001
        pass
    commit_with_retry(db)
    db.refresh(a)
    return {"success": True, "id": a.id}


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: int, db: Session = Depends(get_db),
                        _=Depends(get_current_user)):
    a = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not a:
        raise HTTPException(404, "公告不存在")
    a.is_active = 0
    a.updated_at = datetime.utcnow()
    commit_with_retry(db)
    return {"success": True}


def _serialize(db: Session, a: Announcement) -> dict:
    row = {col.name: getattr(a, col.name) for col in Announcement.__table__.columns}
    row["region_name"] = db.query(Region.name).filter(Region.id == a.region_id).scalar() if a.region_id else None
    if isinstance(row.get("created_at"), datetime):
        row["created_at"] = row["created_at"].isoformat(sep=" ")
    if isinstance(row.get("updated_at"), datetime):
        row["updated_at"] = row["updated_at"].isoformat(sep=" ")
    return row
