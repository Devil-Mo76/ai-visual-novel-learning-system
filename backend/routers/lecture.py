"""讲师一对一辅导路由（需求：用户召唤讲师深入讲解疑难知识点）。

- POST /api/lecture/chat  → SSE 流式返回 {talk_emo, text} 逐段片段
- POST /api/lecture/end   → 清空该剧本的讲师会话记忆

讲师依据：该剧本关联的学习资料全文 + 通用知识（+ 可选网络信息），
会话历史按 script_id 在进程内维护，退出时清空。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Script, Settings
from ..schemas import LectureChatIn, LectureEndIn
from ..services import lecture_service

logger = logging.getLogger("lecture")
router = APIRouter(prefix="/api/lecture", tags=["lecture"])


def _api_config(db: Session) -> tuple[str, str, str]:
    cfg = db.get(Settings, 1)
    api_base = cfg.api_base if cfg else "https://api.siliconflow.cn/v1"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-ai/DeepSeek-V3"
    return api_base, api_key, model


def _resolve_source(db: Session, script_id: int) -> str:
    """取该剧本关联学习资料的正文（讲师优先依据资料回答）。"""
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在，请先进入学习。")
    return (script.document.content if script.document else "") or ""


@router.post("/chat")
def lecture_chat(payload: LectureChatIn, db: Session = Depends(get_db)):
    """讲师流式作答：SSE 逐段推送 {talk_emo, text}。"""
    api_base, api_key, model = _api_config(db)
    if not api_key:
        raise HTTPException(400, "尚未配置有效的 API Key，请先在「设置」中填写。")
    if not payload.question.strip():
        raise HTTPException(400, "提问内容不能为空。")

    source_text = _resolve_source(db, payload.script_id)

    def event_stream():
        try:
            for seg in lecture_service.chat_stream(
                api_base, api_key, model, payload, source_text
            ):
                yield f"data: {json.dumps(seg, ensure_ascii=False)}\n\n"
        except Exception as exc:  # 兜底：流中断也要给前端一个可辨识的结束事件
            logger.error("讲师流式应答异常：%s", exc)
            yield f"data: {json.dumps({'talk_emo': 'sikao', 'text': '（讲师应答中断，请稍后重试。）'}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/end")
def lecture_end(payload: LectureEndIn):
    """退出讲师模式：清空该剧本的会话记忆，让下次进入是全新对话。"""
    lecture_service.clear_lecture_history(payload.script_id)
    logger.info("讲师会话已清空 script_id=%d", payload.script_id)
    return {"ok": True}