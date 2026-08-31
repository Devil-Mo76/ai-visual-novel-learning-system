"""数据库引擎与会话管理（同步 SQLite 驱动，兼顾 Postgres 路径）。"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

# 统一使用同步 SQLite + 可选 Postgres 的 SQLAlchemy 调用方式。
# 出于演示环境的可移植性，采用同步 session（FastAPI 用 Def 依赖注入）。
engine = create_engine(settings.resolved_database_url, connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {})


# SQLite 默认不启用外键约束。开启后：删除文档可级联删剧本，
# 删除用户可级联清理其全部数据（documents/scripts/progress/analytics/lecture_history）。
if settings.resolved_database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """启动时建表（幂等：已有表不会重建）。"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依赖：提供请求级 DB session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()