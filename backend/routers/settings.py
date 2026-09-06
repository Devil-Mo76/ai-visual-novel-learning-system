"""设置路由：API地址 / Key / 模型名 / 连接测试。

安全要点：前端永远拿不到完整 api_key，只返回掩码和「是否已设置」标记。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Settings as SettingsModel
from ..schemas import SettingsIn, SettingsOut, TestResult

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _get_row(db: Session) -> SettingsModel:
    row = db.get(SettingsModel, 1)
    if row is None:
        row = SettingsModel(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}{'*' * (len(key) - 7)}{key[-4:]}"


def _engine_of(row) -> str:
    """读取路由策略（老库无该列时回落 auto，避免 AttributeError）。"""
    eng = (getattr(row, "llm_engine", "") or "auto").strip().lower()
    return eng if eng in ("auto", "local", "cloud") else "auto"


@router.get("", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db)):
    row = _get_row(db)
    return SettingsOut(
        api_base=row.api_base,
        model=row.model,
        web_search=bool(row.web_search),
        demo_mode=bool(row.demo_mode),
        review_mode=(row.review_mode or "smart"),
        llm_engine=_engine_of(row),
        thinking_level=getattr(row, "thinking_level", "high") or "high",
        api_key_set=bool(row.api_key),
        key_masked=_mask(row.api_key),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    row = _get_row(db)
    # 字段留空时保持数据库里的旧值，避免把配置误清空
    if payload.api_base:
        row.api_base = payload.api_base.strip()
    if payload.model:
        row.model = payload.model.strip()
    if payload.api_key:
        row.api_key = payload.api_key.strip()   # Key 留空则保持不变
    if payload.web_search is not None:
        row.web_search = payload.web_search
    if payload.demo_mode is not None:
        row.demo_mode = payload.demo_mode
    if payload.review_mode in ("smart", "naive"):
        row.review_mode = payload.review_mode
    if payload.llm_engine in ("auto", "local", "cloud"):
        row.llm_engine = payload.llm_engine
    if payload.thinking_level in ("high", "medium", "low"):
        row.thinking_level = payload.thinking_level
    db.commit()
    db.refresh(row)
    # 立即把新策略推给路由层（不等下次请求），设置界面切换后马上生效
    from ..services import llm

    llm.set_runtime_engine(_engine_of(row))
    return SettingsOut(
        api_base=row.api_base,
        model=row.model,
        web_search=bool(row.web_search),
        demo_mode=bool(row.demo_mode),
        review_mode=(row.review_mode or "smart"),
        llm_engine=_engine_of(row),
        thinking_level=getattr(row, "thinking_level", "high") or "high",
        api_key_set=bool(row.api_key),
        key_masked=_mask(row.api_key),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/test", response_model=TestResult)
def test_connection(payload: SettingsIn | None = None, db: Session = Depends(get_db)):
    """连通性测试：后端调 DeepSeek 发一次 chat/completions。"""
    row = _get_row(db)
    api_base = (payload.api_base.strip() if payload and payload.api_base else row.api_base)
    api_key = (payload.api_key.strip() if payload and payload.api_key else row.api_key)
    model = (payload.model.strip() if payload and payload.model else row.model) or "deepseek-v4-flash"
    thinking = (payload.thinking_level if payload and payload.thinking_level
                else getattr(row, "thinking_level", None)) or "high"

    if not api_key:
        return TestResult(success=False, message="尚未配置 API Key，请在设置中填写后重试。")
    from ..services.script_engine import _LLMClient
    try:
        _LLMClient(api_base, api_key, model, reasoning_effort=thinking).chat("请回复“连接成功”四个字。")
        return TestResult(success=True, message="连接成功，DeepSeek 已响应。")
    except Exception as exc:
        return TestResult(success=False, message=f"连接失败：{exc}")