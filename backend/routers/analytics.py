"""学习报告聚合接口：各章节答题正确率 + 章节维度雷达图。

数据源：analytics 表（scripts.py 的 answer 判题每次作答都会落一行）。
- GET /api/analytics/overview?script_id=xxx
  返回：雷达图维度（取各章节标题）+ 各章节正确率柱状数据 + 总题数/答对/总正确率。

无 API Key 也能用：本接口只读本地 analytics 表，不调 AI。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Analytics, Script
from ..schemas import AnalyticsOverviewOut

logger = logging.getLogger("analytics")
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewOut)
def overview(script_id: int, db: Session = Depends(get_db)):
    """学习报告概览：各章节正确率柱状 + 章节维度雷达 + 总统计。

    正确率 = 该章答对次数 / 该章总作答次数（每次判题落一行，含 attempts 多次作答）。
    """
    script = db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")

    chapters = script.chapters

    # 统计各章节：总作答次数 与 答对次数
    rows = db.execute(
        select(
            Analytics.chapter_index,
            func.count(Analytics.id),
            func.sum(func.cast(Analytics.is_correct, Integer)),
        )
        .where(Analytics.script_id == script_id)
        .group_by(Analytics.chapter_index)
    ).all()

    # 合并章节标题
    stats: dict[int, list[int]] = {}   # chapter_index -> [total, correct]
    for idx, total, correct in rows:
        stats[int(idx)] = [int(total), int(correct or 0)]

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

    logger.info("学习报告 script_id=%d 总题=%d 答对=%d", script_id, total_questions, total_correct)

    return AnalyticsOverviewOut(
        script_id=script_id,
        script_title=script.title,
        radar=radar,
        chapters_accuracy=chapters_accuracy,
        total_questions=total_questions,
        total_correct=total_correct,
        overall_rate=overall_rate,
    )