"""学习报告聚合接口：各章节答题正确率 + 章节维度雷达图。

数据源：analytics 表（scripts.py 的 answer 判题每次作答都会落一行）。
- GET /api/analytics/overview?script_id=xxx
  返回：雷达图维度（取各章节标题）+ 各章节正确率柱状数据 + 总题数/答对/总正确率。

无 API Key 也能用：本接口只读本地 analytics 表，不调 AI。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Analytics, Script, Settings, User
from ..schemas import AnalyticsOverviewOut, DiagnosisOut
from ..services import mastery

logger = logging.getLogger("analytics")
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _agg_chapters(rows: list[Analytics], chapters: list[dict]) -> tuple[list, list, int, int, float]:
    """按章节聚合正确率 + 总统计（radar + chapters_accuracy）。"""
    stats: dict[int, list[int]] = {}   # chapter_index -> [total, correct]
    for a in rows:
        s = stats.setdefault(a.chapter_index, [0, 0])
        s[0] += 1
        if a.is_correct:
            s[1] += 1

    chapters_accuracy = []
    radar = []
    total_questions = 0
    total_correct = 0
    for i, ch in enumerate(chapters):
        title = ch.get("title", f"第{i+1}章")
        total, correct = stats.get(i, [0, 0])
        rate = round(correct * 100.0 / total, 1) if total else 0.0
        chapters_accuracy.append(
            {
                "chapter_index": i,
                "title": title,
                "correct": correct,
                "total": total,
                "rate": rate,
            }
        )
        radar.append({"name": title, "value": rate})
        total_questions += total
        total_correct += correct

    overall_rate = round(total_correct * 100.0 / total_questions, 1) if total_questions else 0.0
    return chapters_accuracy, radar, total_questions, total_correct, overall_rate


def _agg_time_series(rows: list[Analytics]) -> list[dict]:
    """按作答当天分组：[{date, total, correct, rate}]（作答次数时间线）。"""
    by_day: dict[str, list[int]] = {}
    for a in rows:
        day = a.created_at.strftime("%Y-%m-%d") if a.created_at else "无日期"
        s = by_day.setdefault(day, [0, 0])
        s[0] += 1
        if a.is_correct:
            s[1] += 1
    out = []
    for day, (total, correct) in sorted(by_day.items()):
        rate = round(correct * 100.0 / total, 1) if total else 0.0
        out.append({"date": day, "total": total, "correct": correct, "rate": rate})
    return out


def _agg_type_distribution(rows: list[Analytics]) -> list[dict]:
    """按题型分组：[{quiz_type, correct, total, rate}]。"""
    by_type: dict[str, list[int]] = {}
    for a in rows:
        s = by_type.setdefault(a.quiz_type or "unknown", [0, 0])
        s[0] += 1
        if a.is_correct:
            s[1] += 1
    out = []
    for t, (total, correct) in by_type.items():
        rate = round(correct * 100.0 / total, 1) if total else 0.0
        out.append({"quiz_type": t, "correct": correct, "total": total, "rate": rate})
    return out


def _agg_coverage(rows: list[Analytics], chapters: list[dict]) -> dict:
    """考点覆盖度：已作答过的章节 vs 剧本全部章节。"""
    covered = {a.chapter_index for a in rows}
    return {
        "total_chapters": len(chapters),
        "covered_chapter_indices": sorted(covered),
        "covered_count": len(covered),
    }


@router.get("/overview", response_model=AnalyticsOverviewOut)
def overview(script_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """学习报告概览：各章节正确率柱状 + 章节维度雷达 + 总统计 + 四维扩展。

    数据源：analytics 表（每次判题落一行）。全部聚合在 Python 端完成，
    规避 SQLite / Postgres 日期函数差异。
    """
    script = db.get(Script, script_id)
    if script is None or script.user_id != user.id:
        raise HTTPException(404, "剧本不存在")

    chapters = script.chapters
    rows = db.scalars(
        select(Analytics)
        .where(Analytics.script_id == script_id, Analytics.user_id == user.id)
        .order_by(Analytics.created_at)
    ).all()

    chapters_accuracy, radar, total_questions, total_correct, overall_rate = _agg_chapters(rows, chapters)

    logger.info("学习报告 script_id=%d 总题=%d 答对=%d", script_id, total_questions, total_correct)

    return AnalyticsOverviewOut(
        script_id=script_id,
        script_title=script.title,
        radar=radar,
        chapters_accuracy=chapters_accuracy,
        total_questions=total_questions,
        total_correct=total_correct,
        overall_rate=overall_rate,
        time_series=_agg_time_series(rows),
        type_distribution=_agg_type_distribution(rows),
        coverage=_agg_coverage(rows, chapters),
        total_study_minutes=round(sum(int(a.time_cost or 0) for a in rows) / 60000.0, 1),
        active_days=len({(a.created_at.date()) for a in rows if a.created_at}),
    )


@router.get("/diagnosis", response_model=DiagnosisOut)
def diagnosis(script_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """学情诊断 + 自适应复习推荐：掌握度 / 前置依赖 / 遗忘曲线到期 / 学习时长。

    依据 settings.review_mode 决定智能(smart)或普通(naive)推荐（实验对照）。
    只读本地 analytics，不调 AI。
    """
    script = db.get(Script, script_id)
    if script is None or script.user_id != user.id:
        raise HTTPException(404, "剧本不存在")

    cfg = db.get(Settings, 1)
    review_mode = (cfg.review_mode if cfg else "smart") or "smart"

    rows = db.scalars(
        select(Analytics)
        .where(Analytics.script_id == script_id, Analytics.user_id == user.id)
    ).all()

    data = mastery.diagnose(script, list(rows), review_mode=review_mode)
    logger.info("学情诊断 script_id=%d 复习模式=%s", script_id, review_mode)
    return data