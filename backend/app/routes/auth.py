"""认证路由"""
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from ..database import get_db, commit_with_retry
from ..models import User, Organization, Company, UserCompany
from ..auth import hash_password, verify_password, create_access_token, check_login_limit, record_login_attempt, get_current_user, get_admin_user
from ..services.audit import insert_audit_log

router = APIRouter()


class LoginReq(BaseModel):
    username: str
    password: str

class RegisterReq(BaseModel):
    username: str
    password: str
    # 公司绑定对齐：可选 org_id（桌面端 AUTH_CREATE_USER 传 companyId 时的云端落点）
    org_id: Optional[int] = None

class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    if not check_login_limit(req.username):
        raise HTTPException(429, "登录尝试过多，请1分钟后重试")

    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password):
        record_login_attempt(req.username, False)
        raise HTTPException(401, "用户名或密码错误")

    record_login_attempt(req.username, True)
    user.last_login = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    insert_audit_log(db, username=req.username, role=user.role, action="login", target="auth",
                     target_id=user.id, result="success")
    db.commit()
    token = create_access_token(user.id, user.username, user.role)
    # 公司绑定对齐：返回 org_id（用户归属组织，与桌面端 company_id 对应）
    return {"token": token, "user": {"id": user.id, "username": user.username, "role": user.role, "org_id": user.org_id, "company_ids": user.company_ids}}


@router.post("/logout")
def logout(user: User = Depends(get_current_user)):
    """无状态 JWT：服务端无需销毁会话，仅返回成功（客户端清除本地 token）。"""
    return {"success": True}


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    """管理端用户列表（对齐桌面端 AUTH_LIST_USERS，联表返回 org_id/org_name）。"""
    rows = db.query(User, Organization.name).outerjoin(
        Organization, Organization.id == User.org_id
    ).order_by(User.id).all()
    result = []
    for u, org_name in rows:
        result.append({
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "org_id": u.org_id,
            "org_name": org_name,
            "created_at": u.created_at.isoformat(sep=" ") if u.created_at else None,
            "last_login": u.last_login,
        })
    return result


class CreateUserReq(BaseModel):
    username: str
    password: str
    role: str = "user"
    org_id: Optional[int] = None
    # v1.3.0 多公司绑定：主席（operator）可管多家公司（org_ids 列表 = 组织 id）
    org_ids: Optional[List[int]] = None
    # 兼容：company_ids 列表（公司 id，内部映射到 org_id；桌面端多选传公司 id）
    company_ids: Optional[List[int]] = None


class ResetPasswordReq(BaseModel):
    new_password: str


@router.post("/users")
def create_user(data: CreateUserReq, db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    """管理端创建用户（对齐桌面端 AUTH_CREATE_USER，支持公司绑定 org_id）。"""
    if len(data.username) < 2:
        raise HTTPException(400, "用户名至少2个字符")
    if len(data.password) < 6:
        raise HTTPException(400, "密码至少6个字符")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "用户名已存在")
    if data.org_id is not None:
        org = db.query(Organization).filter(Organization.id == data.org_id).first()
        if not org:
            raise HTTPException(400, "所属公司不存在")
    # v1.3.0 多公司绑定：org_ids（组织 id）或 company_ids（公司 id，需映射）
    if data.company_ids:
        comp_rows = db.query(Company.id, Company.org_id).filter(Company.id.in_(data.company_ids)).all()
        if len(comp_rows) != len(set(data.company_ids)):
            raise HTTPException(400, "存在无效的公司绑定")
        org_ids = [r[1] for r in comp_rows if r[1] is not None]
    else:
        org_ids = data.org_ids or ([data.org_id] if data.org_id is not None else None)
    if org_ids:
        valid = {r[0] for r in db.query(Organization.id).filter(Organization.id.in_(org_ids)).all()}
        invalid = [o for o in org_ids if o not in valid]
        if invalid:
            raise HTTPException(400, f"所属公司不存在: {invalid}")
    user = User(username=data.username, password=hash_password(data.password),
                role=data.role if data.role in ("admin", "operator", "user", "rep") else "user",
                org_id=data.org_id)
    db.add(user)
    commit_with_retry(db)
    # 多公司绑定：写入 user_companies（org_ids 是组织 id，需映射到 company_id）
    if org_ids:
        for oid in org_ids:
            comp = db.query(Company.id).filter(Company.org_id == oid).first()
            if comp:
                db.add(UserCompany(user_id=user.id, company_id=comp[0]))
        commit_with_retry(db)
    return {"id": user.id, "username": user.username, "role": user.role,
            "org_id": user.org_id, "org_ids": org_ids or []}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, data: ResetPasswordReq, db: Session = Depends(get_db),
                   admin: User = Depends(get_admin_user)):
    """管理员重置任意用户密码（对齐桌面端 AUTH_RESET_PASSWORD 校验规则）。"""
    new_pwd = data.new_password
    if len(new_pwd) < 6:
        raise HTTPException(400, "新密码至少6个字符")
    if not any(ch.isalpha() for ch in new_pwd) or not any(ch.isdigit() for ch in new_pwd):
        raise HTTPException(400, "新密码需包含字母和数字")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    target.password = hash_password(new_pwd)
    insert_audit_log(db, username=admin.username, role=admin.role, action="reset_password",
                     target="user", target_id=user_id,
                     new_value=f'{{"username": "{target.username}", "role": "{target.role}"}}')
    db.commit()
    return {"success": True, "isSelf": admin.id == user_id}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    """管理员删除用户（不允许删除自己）。"""
    if admin.id == user_id:
        raise HTTPException(400, "不能删除当前登录的管理员账号")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    insert_audit_log(db, username=admin.username, role=admin.role, action="delete",
                     target="user", target_id=user_id,
                     old_value=f'{{"username": "{target.username}", "role": "{target.role}"}}')
    db.delete(target)
    db.commit()
    return {"success": True}


@router.post("/register")
def register(req: RegisterReq, db: Session = Depends(get_db), x_admin_key: str = Header(default="")):
    # 安全验收 P0：注册接口要求管理密钥，公网匿名注册一律拒绝。
    # 内部使用场景：账号由桌面端统一登录自动建号（/auth/login 自动创建），
    # 或管理员在桌面端用户管理创建后同步；不提供公网自助注册。
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(403, "无管理权限，注册已关闭")
    if len(req.username) < 2:
        raise HTTPException(400, "用户名至少2个字符")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少6个字符")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")

    user = User(username=req.username, password=hash_password(req.password), role="user", org_id=req.org_id)
    db.add(user)
    db.commit()
    return {"message": "注册成功"}


@router.post("/change-password")
def change_password(req: ChangePasswordReq, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(req.old_password, user.password):
        raise HTTPException(400, "原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(400, "新密码至少6个字符")
    user.password = hash_password(req.new_password)
    db.commit()
    return {"message": "密码修改成功"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role, "org_id": user.org_id}
