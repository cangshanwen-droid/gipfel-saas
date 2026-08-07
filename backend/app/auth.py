"""JWT 认证 — PBKDF2 + 盐值，兼容旧版 SHA256"""
import math, time
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.hash import pbkdf2_sha256
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .models import User

security = HTTPBearer()

# ── 登录限流 ─────────────────────────────────────
_login_attempts: dict[str, tuple[int, float]] = {}  # username -> (count, reset_time)

def check_login_limit(username: str) -> bool:
    now = time.time()
    if username in _login_attempts:
        count, reset = _login_attempts[username]
        if now < reset and count >= 5:
            return False
        if now >= reset:
            del _login_attempts[username]
    return True

def record_login_attempt(username: str, success: bool):
    if success:
        _login_attempts.pop(username, None)
    else:
        now = time.time()
        if username in _login_attempts:
            count, reset = _login_attempts[username]
            if now >= reset:
                _login_attempts[username] = (1, now + 60)
            else:
                _login_attempts[username] = (count + 1, reset)
        else:
            _login_attempts[username] = (1, now + 60)

# ── 密码处理 ─────────────────────────────────────
def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pbkdf2_sha256.verify(plain, hashed)

def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "username": username, "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user

def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
