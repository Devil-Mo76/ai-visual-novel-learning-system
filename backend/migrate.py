"""幂等数据库迁移：老表补 user_id 列 + 种子用户 + 新字段扩列。

背景：models.py 已为 documents/scripts/progress 增加 user_id 外键，并新增
analytics / lecture_history 表、scripts 的 goal 与 updated_at 字段；但现有的
learning.db 四表并无这些列。启动时执行本迁移，使既有演示数据可用且物理隔离。

幂等策略（不破坏数据，可重复执行）：
- 对全新库：Base.metadata.create_all 已按 models.py 建全结构，无需处理。
- 对老库：逐表用 PRAGMA table_info 检测缺列 → 缺则 ALTER TABLE ADD COLUMN，
  并回填种子用户 / 默认值；已存在则跳过。

注意（事务处理）：
- SQLite 的 ALTER TABLE 属于 DDL，独立提交；不要在事务上下文（engine.begin）
  里再手动 commit，否则外层提交时会触发 InvalidRequestError。
- 因此这里统一用 engine.connect() + 每步完成后手动 conn.commit()。
- SQLite 对 ADD COLUMN 支持有限（不能加 REFERENCES 约束），故 user_id 先以普通
  列加入，隔离靠应用层过滤 + 删除时的手动级联（与 routers/documents.py 一致）。
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from .config import settings
from .db import SessionLocal, engine


def _table_columns(conn, table: str) -> list[str]:
    """返回某表当前全部列名（PRAGMA table_info）。"""
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]


def _ensure_column(conn, table: str, column: str, column_type: str, default: str) -> None:
    """幂等地为老表补一个列（已存在则跳过）。"""
    cols = _table_columns(conn, table)
    if column in cols:
        return  # 已迁移过，跳过（幂等）
    ddl = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
    if default is not None:
        ddl += f" DEFAULT {default}"
    conn.execute(text(ddl))
    conn.commit()


def _ensure_user_id_column(conn, table: str, seed_user_id: int) -> None:
    """幂等地为老表补上 user_id 列并回填种子用户。"""
    cols = _table_columns(conn, table)
    if "user_id" in cols:
        # 已存在：确保空值也回填（幂等兜底）
        conn.execute(
            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
            {"uid": seed_user_id},
        )
        conn.commit()
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
    conn.commit()
    conn.execute(
        text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": seed_user_id},
    )
    conn.commit()


def _ensure_script_goal_columns(conn) -> None:
    """幂等地为 scripts 表补学习目标匹配度 + 更新时间字段。"""
    _ensure_column(conn, "scripts", "goal_score", "INTEGER", "NULL")
    _ensure_column(conn, "scripts", "goal_comment", "TEXT", "''")
    _ensure_column(conn, "scripts", "updated_at", "DATETIME", "NULL")


def _ensure_analytics_columns(conn) -> None:
    """幂等地为 analytics 表补错题本回溯字段（老库升级路径）。"""
    for col, ctype, dft in (
        ("question_text", "TEXT", "''"),
        ("your_answer", "TEXT", "''"),
        ("correct_answer", "TEXT", "''"),
        ("explain", "TEXT", "''"),
    ):
        _ensure_column(conn, "analytics", col, ctype, dft)


def _seed_user_id() -> int:
    """确保种子用户存在并返回其 id（幂等：已存在则直接返回）。"""
    with SessionLocal() as db:
        from .models import User
        from .security import hash_password

        user = db.scalars(sa.select(User).where(User.username == "demo")).first()
        if user is None:
            user = User(username="demo", password_hash=hash_password("demo123"))
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id


def run_migrations() -> None:
    """入口：老库补 user_id + goal 字段 + analytics 字段 + 种子用户。

    仅对 SQLite 需要（全新库由 create_all 建全）。Postgres 升级建议交给正式迁移工具。
    """
    if not settings.resolved_database_url.startswith("sqlite"):
        return

    # 先建表（确保 users / analytics / lecture_history 等新表存在）
    from .models import Base

    Base.metadata.create_all(bind=engine)

    seed_id = _seed_user_id()

    conn = engine.connect()
    try:
        for table in ("documents", "scripts", "progress"):
            _ensure_user_id_column(conn, table, seed_id)
        _ensure_script_goal_columns(conn)
        _ensure_analytics_columns(conn)
    finally:
        conn.close()