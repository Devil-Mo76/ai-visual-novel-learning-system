"""FastAPI 入口：注册路由 + CORS + 启动建表/迁移 + 结构化日志。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .logger import get_logger
from .errors import http_exception_handler, unhandled_exception_handler
from .migrate import run_migrations
from .routers import analytics
from .routers import auth as auth_router
from .routers import documents, lecture, progress, scripts, settings as settings_router

logger = get_logger()

app = FastAPI(title="AI视觉小说互动式学习系统", version="1.0.0")

# 开发期放开跨域；答辩部署时可在 settings.cors_origins 收窄
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# —— 统一错误响应 {"detail", "error_code"} ——
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth_router.router)
app.include_router(analytics.router)
app.include_router(documents.router)
app.include_router(lecture.router)
app.include_router(scripts.router)
app.include_router(progress.router)
app.include_router(settings_router.router)


@app.on_event("startup")
def _startup() -> None:
    from .db import init_db

    from .logger import setup_logging

    setup_logging()          # Loguru：按日切分文件 + 终端日志，先于一切业务日志
    init_db()                # create_all：保证新表/新列在全新库可用
    run_migrations()         # 老表补 user_id 列 + 种子用户回填（幂等）
    logger.info("服务已启动：数据库 {}", settings.resolved_database_url)


@app.get("/api/health")
def health():
    return {"status": "ok"}