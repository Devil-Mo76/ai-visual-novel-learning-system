"""剧本路由：生成剧本（调 AI）、查询剧本详情。"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Analytics, Document, Script, Settings
from ..schemas import (
    AnswerIn,
    AnswerOut,
    ChapterNode,
    ScriptDetailOut,
    ScriptGenerateIn,
    ScriptGenerateOut,
    ScriptPayload,
    ScriptUpdateIn,
    WrongQuestionOut,
)
from ..services.script_engine import ScriptGenerationError, evaluate_goal_match, generate_script, judge_answer
from ..auth import get_current_user, get_or_create_default_user

logger = logging.getLogger("scripts")
router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.post("/generate", response_model=ScriptGenerateOut)
def generate(payload: ScriptGenerateIn, db: Session = Depends(get_db)):
    doc = db.get(Document, payload.document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在，请先上传学习资料。")

    cfg = db.get(Settings, 1)
    api_base = cfg.api_base if cfg else "https://api.siliconflow.cn/v1"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-ai/DeepSeek-V3"

    final_title = payload.title or doc.title or doc.filename
    try:
        script_payload: ScriptPayload = generate_script(
            api_base=api_base,
            api_key=api_key,
            model=model,
            content=doc.content,
            source=doc.filename,
            title=final_title,
            chapter_count=payload.chapter_count,
            learning_goal=payload.learning_goal,
            quiz_types=payload.quiz_types,
        )
    except ScriptGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 持久化剧本 → 得到 script_id（方案A：整份剧本落库）
    # user_id 归属：无 token 时后端兜底为默认种子用户
    owner = get_or_create_default_user(db)
    script = Script(
        user_id=owner.id,
        document_id=doc.id,
        title=final_title,
        source=doc.filename,
        chapters=script_payload.model_dump(mode="json")["chapters"],
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    logger.info("剧本已生成并落库 script_id=%d", script.id)

    # —— 生成后置：学习目标匹配度校验（轻量 AI 评估）——
    # 评估失败时返回默认值，绝不阻断主流程；score/comment 写入 scripts 行供前端展示。
    goal_eval = evaluate_goal_match(
        api_base=api_base,
        api_key=api_key,
        model=model,
        learning_goal=payload.learning_goal,
        script_payload=script_payload,
    )
    script.goal_score = goal_eval.get("score")
    script.goal_comment = goal_eval.get("comment", "")
    db.commit()
    db.refresh(script)
    logger.info("学习目标匹配度评估完成 script_id=%d score=%s", script.id, script.goal_score)

    return ScriptGenerateOut(
        script_id=script.id,
        script=script_payload,
        goal_score=script.goal_score,
        goal_comment=script.goal_comment,
    )


def _record_analytics(db: Session, script: Script, payload: AnswerIn,
                      is_correct: bool, question_text: str = "",
                      your_answer: str = "", correct_answer: str = "",
                      explain: str = "", attempts: int = 1, time_cost: int = 0):
    """把一次判题结果写入 analytics 表（错题本 / 学习报告的数据源）。

    每次作答落一行；answer 路由的两个分支（选择题本地判定、填空/简答 AI 判题）
    都通过此入口记录，保证「只看错题」「学习报告」有数据可查。"""
    row = Analytics(
        user_id=(get_current_user(db).id if False else 1),  # 占位，实际用 owner
        script_id=script.id,
        chapter_index=payload.chapter_index,
        step_index=payload.step_index,
        quiz_type=payload.quiz_type,
        is_correct=is_correct,
        attempts=attempts,
        time_cost=time_cost,
        question_text=question_text,
        your_answer=your_answer,
        correct_answer=correct_answer,
        explain=explain,
    )
    db.add(row)
    db.commit()


@router.post("/answer", response_model=AnswerOut)
def answer(payload: AnswerIn, db: Session = Depends(get_db)):
    """判题：选择题前端本地比较即可（此处兜底）；填空/简答由 AI 判断。
    简答题：用户复述须覆盖参考要点 70%~80% 才算通过。"""
    script = db.get(Script, payload.script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")

    chapters = script.chapters
    if payload.chapter_index >= len(chapters):
        raise HTTPException(400, "章节索引越界")
    ch = chapters[payload.chapter_index]
    steps = ch.get("steps", [])
    if payload.step_index >= len(steps):
        raise HTTPException(400, "步骤索引越界")
    node = steps[payload.step_index]

    # —— 选择题：前端已本地判，这里兜底作参考 ——
    if payload.quiz_type == "choice":
        correct = payload.picked_index is not None and node.get("answer") == payload.picked_index
        correct_label = node.get("choices")[node["answer"]] if isinstance(node.get("choices"), list) and 0 <= (node.get("answer") or -1) < len(node.get("choices") or []) else ""
        _record_analytics(
            db, script, payload,
            is_correct=correct,
            question_text=node.get("text", ""),
            your_answer=str(node.get("choices")[payload.picked_index] if payload.picked_index is not None and isinstance(node.get("choices"), list) and 0 <= payload.picked_index < len(node.get("choices")) else payload.picked_index),
            correct_answer=correct_label,
            explain=node.get("explain", ""),
        )
        return AnswerOut(
            correct=correct,
            explain=node.get("explain", ""),
            message="选择题本地判定",
        )

    # —— 填空 / 简答：AI 判题 ——
    cfg = db.get(Settings, 1)
    api_base = cfg.api_base if cfg else "https://api.siliconflow.cn/v1"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-ai/DeepSeek-V3"

    if payload.quiz_type == "fill":
        reference = node.get("answer_text") or node.get("explain") or ""
    else:  # short
        points = node.get("reference_points") or []
        reference = "要点：" + "；".join(points) if points else (node.get("explain") or "")

    # 只从用户提供的学习资料中寻找答案：取该剧本关联文档的正文作为判题锚点
    source_text = script.document.content if script.document else ""

    result = judge_answer(
        api_base, api_key, model,
        question=node.get("text", ""),
        reference=reference,
        answer=payload.quote,
        source=source_text,
    )
    explain = result.get("explain", "")
    keywords = result.get("keywords") or []
    if keywords:
        explain = f"{explain}（命中关键词：{'、'.join(str(k) for k in keywords[:4])}）"
    # —— 填空/简答：同样落 analytics（错题本/学习报告数据源）——
    _record_analytics(
        db, script, payload,
        is_correct=bool(result.get("correct")),
        question_text=node.get("text", ""),
        your_answer=payload.quote,
        correct_answer=reference,
        explain=explain,
        attempts=payload.attempts or 1,
        time_cost=payload.time_cost or 0,
    )
    return AnswerOut(correct=result["correct"], explain=explain, message="AI 判题")


@router.get("/{script_id}", response_model=ScriptDetailOut)
def get_script(script_id: int, db: Session = Depends(get_db)):
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")
    return ScriptDetailOut(
        script_id=script.id,
        document_id=script.document_id,
        title=script.title,
        source=script.source,
        chapters=script.chapters,
    )


@router.get("/{script_id}/list")
def get_chapters(script_id: int, db: Session = Depends(get_db)):
    """章节列表 + 背景 key，供前端在加载首章时切背景。"""
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")
    chapters = []
    for i, ch in enumerate(script.chapters):
        chapters.append({"index": i, "id": ch["id"], "title": ch["title"], "background": ch["background"]})
    return {"script_id": script_id, "chapters": chapters}


@router.get("/{script_id}/wrong_questions", response_model=List[WrongQuestionOut])
def wrong_questions(script_id: int, db: Session = Depends(get_db)):
    """错题本：该剧本下所有答错(is_correct=False)的记录，按章节去重。

    - 数据源：analytics 表（answer 路由每次判题都会落一行）。
    - 只看错题复习模式与错题本面板共用此接口。
    """
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")

    wrongs = db.scalars(
        select(Analytics)
        .where(Analytics.script_id == script_id, Analytics.is_correct == False)  # noqa: E712
        .order_by(Analytics.chapter_index, Analytics.step_index)
    ).all()

    seen: set[tuple[int, int]] = set()
    result: list[WrongQuestionOut] = []
    for a in wrongs:
        key = (a.chapter_index, a.step_index)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            WrongQuestionOut(
                chapter_index=a.chapter_index,
                step_index=a.step_index,
                question_text=a.question_text,
                your_answer=a.your_answer,
                correct_answer=a.correct_answer,
                explain=a.explain,
            )
        )
    return result


@router.post("/{script_id}/update", response_model=ScriptDetailOut)
def update_script(script_id: int, payload: ScriptUpdateIn, db: Session = Depends(get_db)):
    """剧本手动更新（人机协同）：直接覆盖 chapters，不重新调用 AI。

    - 请求体 chapters：修改后的完整章节 JSON 数组（仅做格式校验）。
    - 落库后自动刷 updated_at，前端可重载当前剧本。
    """
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")

    script.chapters = payload.chapters  # Pydantic 已做 ScriptPayload 级格式校验
    db.commit()
    db.refresh(script)
    logger.info("剧本手动更新完成 script_id=%d 章节数=%d", script.id, len(script.chapters))

    return ScriptDetailOut(
        script_id=script.id,
        document_id=script.document_id,
        title=script.title,
        source=script.source,
        chapters=script.chapters,
        goal_score=script.goal_score,
        goal_comment=script.goal_comment,
    )