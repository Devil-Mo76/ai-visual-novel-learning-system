"""FastAPI 入口：注册路由 + CORS + 启动建表/迁移 + 结构化日志。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import settings
from .logger import get_logger
from .errors import http_exception_handler, unhandled_exception_handler
from .middleware import MetricsMiddleware, RateLimitMiddleware
from .migrate import run_migrations
from .routers import analytics
from .routers import auth as auth_router
from .routers import documents, lecture, progress, scripts, settings as settings_router
from .routers import llm as llm_router
from .services.metrics import metrics

logger = get_logger()

app = FastAPI(title="AI视觉小说互动式学习系统", version="2.0.0")

# 网络工程强化：按依赖顺序——先限流（防刷）再指标计时（不含被限流丢弃的请求）。
# metrics 在 CORS 之前注册也可，保持简单顺序即可。
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitMiddleware)

# 开发期放开跨域；答辩部署时在 .env 的 CORS_ORIGINS 收窄（生产建议同源+明确白名单）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(llm_router.router)   # 模型路由：状态/探测/切换/自测/基准


@app.on_event("startup")
def _startup() -> None:
    from .db import init_db

    from .logger import setup_logging

    setup_logging()          # Loguru：按日切分文件 + 终端日志，先于一切业务日志
    init_db()                # create_all：保证新表/新列在全新库可用
    run_migrations()         # 老表补 user_id 列 + 种子用户回填（幂等）
    _start_llm_watchdog()    # 模型路由：同步策略 + 启动云端健康看门狗
    logger.info("服务已启动：数据库 {}", settings.resolved_database_url)


def _start_llm_watchdog() -> None:
    """同步数据库里的路由策略，并启动云端健康看门狗（断网恢复后自动回切）。"""
    from .db import SessionLocal
    from .models import Settings as SettingsModel
    from .services import llm as llm_service

    try:
        with SessionLocal() as db:
            row = db.get(SettingsModel, 1)
            if row is not None:
                eng = (getattr(row, "llm_engine", "") or "auto").strip().lower()
                llm_service.set_runtime_engine(eng if eng in ("auto", "local", "cloud") else None)
    except Exception as exc:
        logger.warning("同步模型路由策略失败（回落到 .env 配置）：{}", exc)

    def _cfg_getter(field: str):
        def _get() -> str:
            try:
                with SessionLocal() as db:
                    row = db.get(SettingsModel, 1)
                    return (getattr(row, field, "") if row else "") or ""
            except Exception:
                return ""
        return _get

    llm_service.start_watchdog(_cfg_getter("api_base"), _cfg_getter("api_key"))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/metrics", response_class=PlainTextResponse)
def metrics_endpoint():
    """Prometheus 文本格式指标（网络可观测性，供 Prometheus 抓取）。"""
    return metrics.render_text()