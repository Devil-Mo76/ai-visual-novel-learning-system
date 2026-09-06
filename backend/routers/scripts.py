"""剧本路由：生成剧本（调 AI）、查询剧本详情。"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..db import get_db
from ..models import Analytics, Document, Script, Settings, User
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
from datetime import datetime, timedelta, timezone
from .. import demo_data
from ..services import knowledge_base
from ..services.script_engine import (
    ScriptGenerationError,
    ScriptRouteUnavailable,
    evaluate_goal_match,
    evaluate_script_quality,
    generate_script,
    judge_answer,
    judge_answer_local,
)
from ..auth import get_current_user
from ..services.metrics import metrics

logger = logging.getLogger("scripts")
router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _get_owned_script(db: Session, current_user: User, script_id: int) -> Script:
    """按归属校验取剧本：必须属于当前用户，否则 404（多用户隔离）。"""
    script = db.get(Script, script_id)
    if script is None or script.user_id != current_user.id:
        raise HTTPException(404, "剧本不存在")
    return script


def _ensure_demo_doc(db: Session, owner: User) -> Document:
    """演示模式：为当前用户造一份样例文档（无则创建，有则复用最新一份）。"""
    from .. import demo_data

    existing = db.scalars(
        select(Document).where(Document.user_id == owner.id).order_by(Document.id.desc()).limit(1)
    ).first()
    if existing:
        return existing
    doc = Document(
        user_id=owner.id,
        filename="操作系统基础演示资料.docx",
        title=demo_data.SAMPLE_DOCUMENT_TITLE,
        content=demo_data.SAMPLE_DOCUMENT_CONTENT,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/generate", response_model=ScriptGenerateOut)
def generate(payload: ScriptGenerateIn, db: Session = Depends(get_db), owner: User = Depends(get_current_user)):
    cfg = db.get(Settings, 1)
    demo_mode = bool(cfg.demo_mode) if cfg else False

    doc = db.get(Document, payload.document_id)
    if doc is None:
        if demo_mode:
            doc = _ensure_demo_doc(db, owner)     # 演示模式：无资料则造一份样例
        else:
            raise HTTPException(404, "文档不存在，请先上传学习资料。")

    api_base = cfg.api_base if cfg else "https://api.deepseek.com"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-v4-flash"
    # 思考强度：高/中/低 → high/medium/low，缺省 high
    thinking = (getattr(cfg, "thinking_level", None) or "high") if cfg else "high"

    # 是否因「云端不可达 + 本地不可用」而降级到了 P1 离线样例剧本
    offline_fallback = False

    if demo_mode:
        # 演示模式：不走 AI，直接返回内置样例剧本
        # 注意：此处不能再写 `from .. import demo_data`，否则 demo_data 会变成
        # generate() 的局部变量，非演示模式走降级分支时引用它即抛 UnboundLocalError。
        script_payload = ScriptPayload.model_validate(demo_data.SAMPLE_SCRIPT)
        final_title = demo_data.SAMPLE_SCRIPT["title"]
        logger.info("演示模式：使用内置样例剧本（未调 AI）")
    else:
        final_title = payload.title or doc.title or doc.filename
        try:
            t0 = time.perf_counter()
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
                reasoning_effort=thinking,
            )
            metrics.record_ai("generate", time.perf_counter() - t0)
        except ScriptRouteUnavailable as exc:
            # —— 云端-边缘混合降级的核心落点 ——
            # 云端不可达（断网/超时/无 Key）且本地模型不可用时，不报错中断，
            # 改用 P1「离线样例剧本」兜底，保证断网场景仍可走完「生成→学习→答题」。
            logger.warning("模型路由不可用，降级为离线样例剧本：%s", exc)
            script_payload = ScriptPayload.model_validate(demo_data.SAMPLE_SCRIPT)
            final_title = f"{final_title}（离线样例·云端不可用）"
            offline_fallback = True
        except ScriptGenerationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # 持久化剧本 → 得到 script_id（方案A：整份剧本落库）
    script = Script(
        user_id=owner.id,
        document_id=doc.id,
        title=final_title,
        source=doc.filename if not (demo_mode or offline_fallback) else demo_data.SAMPLE_SCRIPT["source"],
        chapters=script_payload.model_dump(mode="json")["chapters"],
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    logger.info("剧本已生成并落库 script_id=%d", script.id)

    # —— 生成后置：学习目标匹配度校验（轻量 AI 评估，演示模式跳过）——
    if demo_mode or offline_fallback:
        script.goal_score = None
        script.goal_comment = (
            "演示模式：内置样例剧本，未做学习目标匹配度评估。"
            if demo_mode else
            "离线降级：云端不可达且本地模型不可用，已改用内置样例剧本，未做学习目标匹配度评估。"
        )
        quality_score = None
        quality_comment = "演示模式：未做生成质量评估。" if demo_mode else "离线降级：未做生成质量评估。"
    else:
        goal_eval = evaluate_goal_match(
            api_base=api_base,
            api_key=api_key,
            model=model,
            learning_goal=payload.learning_goal,
            script_payload=script_payload,
        )
        script.goal_score = goal_eval.get("score")
        script.goal_comment = goal_eval.get("comment", "")

        # —— 生成质量自动评估 + 自修复（③）：评分<60 时按 issues 重生成一次 ——
        quality_score = None
        quality_comment = ""
        if api_key:
            q = evaluate_script_quality(api_base, api_key, model, script_payload)
            if q.get("score") is not None and q["score"] < 60 and q.get("issues"):
                hint = "；".join(q["issues"])
                logger.info("生成质量偏低 %s 分，按问题重生成一次：%s", q["score"], hint)
                try:
                    script_payload = generate_script(
                        api_base=api_base, api_key=api_key, model=model,
                        content=doc.content, source=doc.filename, title=final_title,
                        chapter_count=payload.chapter_count,
                        learning_goal=payload.learning_goal,
                        quiz_types=payload.quiz_types,
                        quality_hint=hint,
                        reasoning_effort=thinking,
                    )
                    script.chapters = script_payload.model_dump(mode="json")["chapters"]
                    q = evaluate_script_quality(api_base, api_key, model, script_payload)
                except ScriptGenerationError:
                    pass
            quality_score = q.get("score")
            quality_comment = "；".join(q.get("issues") or [])

    script.quality_score = quality_score
    script.quality_comment = quality_comment
    db.commit()
    db.refresh(script)
    logger.info("剧本评估完成 script_id=%d goal=%s quality=%s",
                script.id, script.goal_score, script.quality_score)

    return ScriptGenerateOut(
        script_id=script.id,
        script=script_payload,
        goal_score=script.goal_score,
        goal_comment=script.goal_comment,
        quality_score=quality_score,
        quality_comment=quality_comment,
    )


def _record_analytics(db: Session, script: Script, payload: AnswerIn,
                      is_correct: bool, question_text: str = "",
                      your_answer: str = "", correct_answer: str = "",
                      explain: str = "", attempts: int = 1, time_cost: int = 0,
                      retested: bool = False):
    """把一次判题结果写入 analytics 表（错题本 / 学习报告的数据源）。

    每次作答落一行；answer 路由的两个分支（选择题本地判定、填空/简答 AI 判题）
    都通过此入口记录，保证「只看错题」「学习报告」有数据可查。"""
    row = Analytics(
        user_id=script.user_id,  # 归属剧本所有者（多用户隔离）
        script_id=script.id,
        chapter_index=payload.chapter_index,
        step_index=payload.step_index,
        quiz_type=payload.quiz_type,
        is_correct=is_correct,
        retested=retested,
        attempts=attempts,
        time_cost=time_cost,
        question_text=question_text,
        your_answer=your_answer,
        correct_answer=correct_answer,
        explain=explain,
    )
    db.add(row)
    db.commit()


def _mark_retested(db: Session, script_id: int, chapter_index: int, step_index: int) -> int:
    """复习模式答对时，把该题所有 is_correct=False 的历史记录置 retested=True。

    只标记不删除，保留完整作答历史供报告趋势使用；错题本/只看错题据此筛选「待复练」。
    同时写入 retested_at（本次成功复练时间）与 review_count（复练阶段）供遗忘曲线排期。
    返回受影响行数。"""
    rows = db.scalars(
        select(Analytics).where(
            Analytics.script_id == script_id,
            Analytics.chapter_index == chapter_index,
            Analytics.step_index == step_index,
            Analytics.is_correct == False,  # noqa: E712
        )
    ).all()
    now = datetime.now(timezone.utc)
    count = 0
    for r in rows:
        r.retested = True
        r.retested_at = now
        r.review_count = int(r.review_count or 0) + 1
        count += 1
    db.commit()
    return count


@router.post("/answer", response_model=AnswerOut)
def answer(payload: AnswerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """判题：选择题前端本地比较即可（此处兜底）；填空/简答由 AI 判断。
    简答题：用户复述须覆盖参考要点 70%~80% 才算通过。"""
    script = _get_owned_script(db, user, payload.script_id)

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
            retested=payload.retested,
        )
        # 复习模式答对：把该题历史错题记录标记为「已复练」
        if payload.retested and correct:
            _mark_retested(db, script.id, payload.chapter_index, payload.step_index)
        return AnswerOut(
            correct=correct,
            explain=node.get("explain", ""),
            message="选择题本地判定",
        )

    # —— 填空 / 简答：AI 判题 ——
    cfg = db.get(Settings, 1)
    api_base = cfg.api_base if cfg else "https://api.deepseek.com"
    api_key = cfg.api_key if cfg else ""
    model = cfg.model if cfg else "deepseek-v4-flash"
    # 思考强度：高/中/低 → high/medium/low，缺省 high
    thinking = (getattr(cfg, "thinking_level", None) or "high") if cfg else "high"

    if payload.quiz_type == "fill":
        reference = node.get("answer_text") or node.get("explain") or ""
    else:  # short
        points = node.get("reference_points") or []
        reference = "要点：" + "；".join(points) if points else (node.get("explain") or "")

    # 判题锚点：优先从「本地知识库」按题干检索最相关片段；若该文档没建库
    # 或无命中，则回退到整篇资料（截前 6000 字，兼容历史未建库文档）。
    source_text = ""
    doc = script.document if script.document else None
    if doc is not None and doc.content:
        kb_root = Path(app_settings.knowledge_dir)
        hits = knowledge_base.retrieve(
            script.document_id, node.get("text", ""), kb_root, top_k=3
        )
        if hits:
            source_text = "\n\n".join(h["text"] for h in hits)
        else:
            # 兜底：整篇截前 6000 字（judge_answer 内部还会再限长）
            source_text = doc.content
            if doc.chunk_count == 0:
                # 知识库未建（如演示文档），尝试即时补建以便后续复用
                try:
                    meta = knowledge_base.build_kb(
                        doc.id, doc.filename, doc.content, kb_root
                    )
                    doc.chunk_count = meta.chunk_count
                    db.commit()
                except Exception:  # noqa: BLE001
                    pass

    # 演示模式：走关键词启发式兜底，完全不调 AI（答辩断网也能判题）。
    # 非演示模式一律交给 judge_answer：由 llm 路由层决定用本地 Qwen 还是云端
    # DeepSeek；若两者都不可用，judge_answer 内部会自行退回启发式判题。
    demo_mode = bool(cfg.demo_mode)
    if demo_mode:
        result = judge_answer_local(
            node.get("text", ""),
            reference=reference,
            answer=payload.quote,
        )
        result["engine"] = "heuristic"
    else:
        result = judge_answer(
            api_base, api_key, model,
            question=node.get("text", ""),
            reference=reference,
            answer=payload.quote,
            source=source_text,
            reasoning_effort=thinking,
        )
    explain = result.get("explain", "")
    keywords = result.get("keywords") or []
    if keywords:
        explain = f"{explain}（命中关键词：{'、'.join(str(k) for k in keywords[:4])}）"
    correct = bool(result.get("correct"))
    # —— 填空/简答：同样落 analytics（错题本/学习报告数据源）——
    _record_analytics(
        db, script, payload,
        is_correct=correct,
        question_text=node.get("text", ""),
        your_answer=payload.quote,
        correct_answer=reference,
        explain=explain,
        attempts=payload.attempts or 1,
        time_cost=payload.time_cost or 0,
        retested=payload.retested,
    )
    # 复习模式答对：把该题历史错题记录标记为「已复练」
    if payload.retested and correct:
        _mark_retested(db, script.id, payload.chapter_index, payload.step_index)
    return AnswerOut(correct=correct, explain=explain, message="AI 判题")


@router.get("/{script_id}", response_model=ScriptDetailOut)
def get_script(script_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    script = _get_owned_script(db, user, script_id)
    return ScriptDetailOut(
        script_id=script.id,
        document_id=script.document_id,
        title=script.title,
        source=script.source,
        chapters=script.chapters,
        goal_score=script.goal_score,
        goal_comment=script.goal_comment,
        quality_score=script.quality_score,
        quality_comment=script.quality_comment,
    )


@router.get("/{script_id}/list")
def get_chapters(script_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """章节列表 + 背景 key，供前端在加载首章时切背景。"""
    script = _get_owned_script(db, user, script_id)
    chapters = []
    for i, ch in enumerate(script.chapters):
        chapters.append({"index": i, "id": ch["id"], "title": ch["title"], "background": ch["background"]})
    return {"script_id": script_id, "chapters": chapters}


@router.get("/{script_id}/wrong_questions", response_model=List[WrongQuestionOut])
def wrong_questions(script_id: int, status: str = "pending", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """错题本：该剧本下所有答错(is_correct=False)的记录，按 章节+步骤 去重。

    - 数据源：analytics 表（answer 路由每次判题都会落一行）。
    - status=pending（默认）：只返回「待复练」错题（retested=False）。
      status=all：返回全部错题记录状态（含已复练），供独立错题本面板。
    - 只看错题复习模式与错题本面板共用此接口。
    """
    script = _get_owned_script(db, user, script_id)

    q = select(Analytics).where(
        Analytics.script_id == script_id, Analytics.is_correct == False  # noqa: E712
    )
    if status != "all":
        q = q.where(Analytics.retested == False)  # noqa: E712
    wrongs = db.scalars(q.order_by(Analytics.chapter_index, Analytics.step_index)).all()

    # 按 (chapter,step) 去重：取「最新一条」作为展示，并累计该题答错次数
    latest: dict[tuple[int, int], tuple[Analytics, int]] = {}
    for a in wrongs:
        key = (a.chapter_index, a.step_index)
        count = latest.get(key, (None, 0))[1] + 1
        latest[key] = (a, count)

    today = datetime.now(timezone.utc).date()

    def forgetting_curve(a: Analytics, wrong_count: int) -> tuple[int, str, bool]:
        """按遗忘曲线排期：interval = min(2^review_count, 30) 天。

        返回 (review_count, next_due_iso, due_now)。从未复练 → 今日复习。
        """
        review_count = int(a.review_count or 0)
        base = a.retested_at or a.created_at or datetime.now(timezone.utc)
        interval_days = min(2 ** max(review_count, 0), 30) if a.retested_at is not None else 0
        next_due = (base + timedelta(days=interval_days)) if a.retested_at is not None else base
        due_now = next_due.date() <= today
        return review_count, (next_due.isoformat()[:10] if hasattr(next_due, "isoformat") else str(next_due)), due_now

    result: list[WrongQuestionOut] = []
    for key in sorted(latest.keys()):
        a, count = latest[key]
        review_count, next_due, due_now = forgetting_curve(a, count)
        result.append(
            WrongQuestionOut(
                chapter_index=a.chapter_index,
                step_index=a.step_index,
                question_text=a.question_text,
                your_answer=a.your_answer,
                correct_answer=a.correct_answer,
                explain=a.explain,
                retested=a.retested,
                wrong_count=count,
                review_count=review_count,
                next_due=next_due,
                due_now=due_now,
            )
        )
    return result


@router.post("/{script_id}/wrong_questions/{chapter_index}/{step_index}/retest")
def mark_retested(script_id: int, chapter_index: int, step_index: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """错题本面板「标记已练」：把该题所有 is_correct=False 记录置 retested=True。

    与 answer 路由复习答对的置位逻辑共用 _mark_retested。返回受影响条数。
    """
    _get_owned_script(db, user, script_id)   # 归属校验（404 否则）
    count = _mark_retested(db, script_id, chapter_index, step_index)
    return {"script_id": script_id, "chapter_index": chapter_index, "step_index": step_index, "marked": count}


@router.post("/{script_id}/update", response_model=ScriptDetailOut)
def update_script(script_id: int, payload: ScriptUpdateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """剧本手动更新（人机协同）：直接覆盖 chapters，不重新调用 AI。

    - 请求体 chapters：修改后的完整章节 JSON 数组（仅做格式校验）。
    - 落库后自动刷 updated_at，前端可重载当前剧本。
    """
    script = _get_owned_script(db, user, script_id)

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
        quality_score=script.quality_score,
        quality_comment=script.quality_comment,
    )