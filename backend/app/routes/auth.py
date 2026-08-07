"""认证路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..database import get_db
from ..models import User
from ..auth import hash_password, verify_password, create_access_token, check_login_limit, record_login_attempt, get_current_user

router = APIRouter()


class LoginReq(BaseModel):
    username: str
    password: str

class RegisterReq(BaseModel):
    username: str
    password: str

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
    token = create_access_token(user.id, user.username, user.role)
    return {"token": token, "user": {"id": user.id, "username": user.username, "role": user.role}}


@router.post("/register")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    if len(req.username) < 2:
        raise HTTPException(400, "用户名至少2个字符")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少6个字符")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")

    user = User(username=req.username, password=hash_password(req.password), role="user")
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
    return {"id": user.id, "username": user.username, "role": user.role}
