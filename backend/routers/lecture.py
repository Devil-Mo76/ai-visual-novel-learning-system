"""讲师一对一辅导路由（需求：用户召唤讲师深入讲解疑难知识点）。

- POST /api/lecture/chat  → SSE 流式返回 {talk_emo, text} 逐段片段
- POST /api/lecture/end   → 清空该剧本、该用户的讲师会话记忆
- GET  /api/lecture/history → 只读历史（落库 lecture_history 表）

讲师依据：该剧本关联的学习资料全文 + 通用知识（+ 可选联网检索摘要），
会话历史按 (user_id, script_id) 持久化在 lecture_history 表，退出时清空。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings as app_settings
from ..db import get_db
from ..models import LectureHistory, Script, Settings, User
from ..schemas import LectureChatIn, LectureEndIn, LectureHistoryRecordOut
from ..services import knowledge_base, lecture_service, llm
from pathlib import Path

logger = logging.getLogger("lecture")
router = APIRouter(prefix="/api/lecture", tags=["lecture"])


def _api_config(db: Session) -> tuple[str, str, str, str]:
    """(api_base, api_key, model, thinking_level)"""
    cfg = db.get(Settings, 1)
    api_base = cfg.api_base if cfg else "https://api.deepseek.com"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-v4-flash"
    thinking = (getattr(cfg, "thinking_level", None) or "high") if cfg else "high"
    return api_base, api_key, model, thinking


def _use_web_search(db: Session) -> bool:
    cfg = db.get(Settings, 1)
    return bool(cfg and cfg.web_search)


def _resolve_source(db: Session, user, script_id: int, question: str = "") -> str:
    """取该剧本关联资料的「本地知识库命中片段」作为讲师上下文。

    优先从 knowledge/kb_{doc_id}/ 按用户问题检索最相关几段（比整篇更聚焦、更快）；
    若该文档未建库或无命中，回退到整篇资料前 6000 字（兼容历史未建库文档）。
    同时校验剧本归属。
    """
    script = db.get(Script, script_id)
    if script is None or script.user_id != user.id:
        raise HTTPException(404, "剧本不存在，请先进入学习。")
    doc = script.document
    if doc is None or not doc.content:
        return ""
    kb_root = Path(app_settings.knowledge_dir)
    if question and question.strip():
        hits = knowledge_base.retrieve(doc.id, question, kb_root, top_k=4)
        if hits:
            return "\n\n".join(h["text"] for h in hits)
        # 无命中：补建库（如历史文档），下次即可检索
        if getattr(doc, "chunk_count", 0) == 0:
            try:
                from ..services import knowledge_base as _kb
                meta = _kb.build_kb(doc.id, doc.filename, doc.content, kb_root)
                doc.chunk_count = meta.chunk_count
                db.commit()
            except Exception:  # noqa: BLE001
                pass
    return doc.content[:6000]


def _demo_chat_segs(question: str, context: str) -> list[dict]:
    """演示模式的内置讲稿（不调 AI）：围绕用户问题组织一两段讲解。"""
    ctx = context.strip()
    q = question.strip()[:80]
    base = [(
        "jiangjie",
        f"（演示模式：未调用 AI）关于『{q}』，你可以先记住它的核心定义，再结合例子理解。"
        f"{"当前上下文：" + ctx if ctx else ""}"
    )]
    return [
        {"talk_emo": emo, "text": text} for (emo, text) in base
    ] + [{"talk_emo": "kaixin", "text": "你可以在「设置」里填入 API Key 并联网后，得到更深入的讲解。──"}]


@router.post("/chat")
def lecture_chat(payload: LectureChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """讲师流式作答：SSE 逐段推送 {talk_emo, text}。"""
    api_base, api_key, model, thinking = _api_config(db)
    if not payload.question.strip():
        raise HTTPException(400, "提问内容不能为空。")

    user_id = user.id
    demo_mode = bool((db.get(Settings, 1) or Settings()).demo_mode)

    # 演示模式，或「无 Key 且本地模型也不可用」→ 内置讲稿。
    # 装了本地 Qwen 时，即使无 Key / 断网，讲师仍可由本地模型实时作答。
    if demo_mode or (not api_key and not llm.local_available()):
        segs = _demo_chat_segs(payload.question, payload.context)

        def event_stream():
            for seg in segs:
                yield f"data: {json.dumps(seg, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if not api_key:
        raise HTTPException(400, "尚未配置有效的 API Key，请先在「设置」中填写。")

    source_text = _resolve_source(db, user, payload.script_id, payload.question)
    use_web_search = _use_web_search(db)

    def event_stream():
        try:
            for seg in lecture_service.chat_stream(
                api_base,
                api_key,
                model,
                payload,
                source_text,
                use_web_search=use_web_search,
                db=db,
                user_id=user_id,
                thinking_level=thinking,
            ):
                yield f"data: {json.dumps(seg, ensure_ascii=False)}\n\n"
        except Exception as exc:  # 兜底：流中断也要给前端一个可辨识的结束事件
            logger.error("讲师流式应答异常：%s", exc)
            yield f"data: {json.dumps({'talk_emo': 'sikao', 'text': '（讲师应答中断，请稍后重试。）'}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history", response_model=list[LectureHistoryRecordOut])
def lecture_history_query(script_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取某剧本该用户的讲师历史对话（只读），展示为聊天气泡。

    数据源：lecture_history 表（user/assistant 交替）。无记录时返回空列表。
    """
    rows = db.scalars(
        select(LectureHistory)
        .where(LectureHistory.user_id == user.id, LectureHistory.script_id == script_id)
        .order_by(LectureHistory.created_at, LectureHistory.id)
    ).all()
    return [
        LectureHistoryRecordOut(
            id=r.id,
            role=r.role,
            content=r.content or "",
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/end")
def lecture_end(payload: LectureEndIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """退出讲师模式：清空该剧本该用户的讲师会话记忆。"""
    lecture_service.clear_lecture_history(db, user.id, payload.script_id)
    logger.info("讲师会话已清空 user_id=%d script_id=%d", user.id, payload.script_id)
    return {"ok": True}
