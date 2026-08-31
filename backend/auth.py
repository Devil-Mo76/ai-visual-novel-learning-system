"""认证依赖：从 Authorization 头解析当前登录用户。

设计要点（多用户隔离 + 前端未接通时的兜底）：
- 正常带 token：Authorization: Bearer <jwt> → 解析出 user_id → 查 users 表。
- 无 token / 无效 token / 用户不存在：**回退到默认种子用户（user_id=1）**，
  保证当前仍为「模拟登录」的前端（不传 token）流程不断、数据归属到种子用户。
  这样隔离架构即刻生效，前端后续接上真实 token 即自动切到各自用户。
"""

from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .security import decode_access_token, hash_password

# 默认种子用户（user_id=1）：承载无 token（模拟登录）请求的全部数据；
# 也是现有演示数据迁移后的归属用户。
DEFAULT_USERNAME = "demo"
DEFAULT_PASSWORD = "demo123"


def get_or_create_default_user(db: Session) -> User:
    """确保种子用户存在并返回（幂等：已存在则直接返回）。"""
    user = db.get(User, 1) or _by_username(db, DEFAULT_USERNAME)
    if user:
        return user
    user = User(
        username=DEFAULT_USERNAME,
        password_hash=hash_password(DEFAULT_PASSWORD),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _by_username(db: Session, username: str) -> User | None:
    from sqlalchemy import select

    return db.scalars(select(User).where(User.username == username)).first()


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    """当前登录用户依赖：优先 token，兜底默认种子用户。"""
    user = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        user_id = decode_access_token(token)
        if user_id is not None:
            user = db.get(User, user_id)
    # 无 token / 失效 / 兜底：一律落到默认种子用户
    if user is None:
        user = get_or_create_default_user(db)
    return user