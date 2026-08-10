"""通知中心写入（对齐桌面端 notification.repo 的领域触发方法）"""
from ..models import Notification, User


def notify_user(db, user_id, title: str, content: str = "", type_: str = "system", link: str = ""):
    if not user_id:
        return
    db.add(Notification(user_id=user_id, title=title, content=content, type=type_, link=link))


def _user_ids_by_role(db, roles):
    if not roles:
        return []
    return [u.id for u in db.query(User).filter(User.role.in_(roles)).all()]


def notify_admins(db, title: str, content: str = "", type_: str = "system", link: str = ""):
    for uid in _user_ids_by_role(db, ["admin"]):
        notify_user(db, uid, title, content, type_, link)


def notify_all(db, title: str, content: str = "", type_: str = "system", link: str = ""):
    for uid in [u.id for u in db.query(User).all()]:
        notify_user(db, uid, title, content, type_, link)


def notify_user_by_username(db, username, title: str, content: str = "", type_: str = "system", link: str = ""):
    """按用户名通知；用户不存在时回退通知 admin（对齐桌面端）。"""
    if username:
        u = db.query(User).filter(User.username == username).first()
        if u:
            notify_user(db, u.id, title, content, type_, link)
            return
    notify_admins(db, title, content, type_, link)


def notify_account_managers(db, title: str, content: str = "", type_: str = "system", link: str = ""):
    for uid in _user_ids_by_role(db, ["admin", "operator"]):
        notify_user(db, uid, title, content, type_, link)
