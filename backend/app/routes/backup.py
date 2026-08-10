"""备份信息（P0-1 补齐：db:info / db:auto-backup）

云端为共享数据库：不提供文件级备份/恢复（那是桌面端本地能力），
仅返回数据库元信息；auto-backup 执行 WAL checkpoint + 返回库大小，
供管理端「服务器状态」展示。
"""
import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import get_admin_user
from ..config import settings
from ..database import engine, get_db
from ..models import User

router = APIRouter()


@router.get("/info")
def db_info(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if db_path == ":memory:" or db_path.startswith("file:"):
        db_path = "in-memory"
    size = 0
    if db_path != "in-memory" and os.path.exists(db_path):
        size = os.path.getsize(db_path)
    size_formatted = f"{size / (1024 * 1024):.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.0f} KB"
    table_count = db.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")).scalar() or 0
    return {
        "path": db_path,
        "size": size,
        "size_formatted": size_formatted,
        "table_count": table_count,
    }


@router.get("/auto")
def auto_backup(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    """自动备份（云端语义：WAL checkpoint 落盘 + 返回库大小；不做文件拷贝）。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:  # noqa: BLE001
        pass
    info = db_info(db)
    return {"success": True, "path": info["path"], "size": info["size"]}
