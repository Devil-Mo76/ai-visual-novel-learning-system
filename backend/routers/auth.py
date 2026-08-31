"""用户认证路由：注册 + 登录（JWT 签发）。\]

- POST /api/auth/register——创建新用户（用户名唯一；密码哈希后入库）。
- POST /api/auth/login——校验用户名/密码，签发 JWT（access_token）。
- GET /api/auth/me——返回当前登录用户（带 token 或兜底种子用户）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        created_at=user.created_at.isoformat(),
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    """注册并直接返回 token（注册即登录）。用户名重复返回 409。"""
    exists = db.scalars(select(User).where(User.username == payload.username)).first()
    if exists:
        raise HTTPException(409, "用户名已被注册，请换一个。")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return TokenOut(access_token=token, token_type="bearer", user=_user_out(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """登录：校验用户名/密码，签发 JWT。"""
    user = db.scalars(select(User).where(User.username == payload.username)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误。")

    token = create_access_token(user.id)
    return TokenOut(access_token=token, token_type="bearer", user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """返回当前登录用户（无 token 时为兜底种子用户）。"""
    return _user_out(current_user)