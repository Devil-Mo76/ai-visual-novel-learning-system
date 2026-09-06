"""学情诊断与自适应复习推荐（智能学情分析的主线算法）。

提供：
- compute_mastery：每个知识点的掌握度（0~1），基于作答正确性与"新鲜度"加权。
- build_prereq_chain：按章节顺序构成前置依赖链（ch_i → ch_{i+1}）。
- diagnose：综合掌握度 / 遗忘曲线到期 / 前置依赖，输出每个知识点的状态与推荐动作，
  以及建议的复习优先级；review_mode=naive 时退化为"按章节顺序"的普通复习（对照实验）。

掌握度公式（轻量可解释，非黑盒）：
  mastery = Σ(权重_i × 正确性_i) / Σ(权重_i)
  权重_i = 1 / (1 + 距今天数)     # 越近的作答越有参考价值
  正确性_i = 1(答对) / 0(答错)
  若该知识点已有成功复练（retested），额外 +0.15，封顶 1。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("mastery")

# 掌握度低于该阈值判为"薄弱"
WEAK_THRESHOLD = 0.4


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _as_aware(dt: datetime | None) -> datetime | None:
    """把数据库取出的 naive datetime 按 UTC 补齐 tzinfo。

    SQLite 存的 DateTime 是 naive（无时区），直接与
    datetime.now(timezone.utc)（aware）做减法或比较会抛：
    "can't subtract offset-naive and offset-aware datetimes"。
    统一在此归一，保证掌握度衰减、遗忘曲线排期都能正常计算。
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def compute_mastery(rows: list) -> float:
    """rows：该知识点的作答记录（Analytics），返回 0~1 掌握度。"""
    now = datetime.now(timezone.utc)
    score = 0.0
    weight_sum = 0.0
    for a in rows:
        created = _as_aware(a.created_at) or now
        age_days = max((now - created).days if hasattr(created, "day") else 0, 0)
        w = 1.0 / (1.0 + age_days)
        score += w * (1.0 if a.is_correct else 0.0)
        weight_sum += w
    mastery = score / weight_sum if weight_sum else 0.0
    # 成功复练过的知识点：掌握倾向更强（+0.15，封顶 1）
    if any(getattr(a, "retested", False) for a in rows):
        mastery = min(mastery + 0.15, 1.0)
    return round(mastery, 2)


def chapter_has_due(rows: list, today: date) -> bool:
    """该知识点是否存在"到期待复习"的错题（沿用遗忘曲线：retested_at + min(2^n,30)天）。"""
    for a in rows:
        if a.retested or a.is_correct:
            # 只看未复练的错题：若已复练则看是否到期
            if a.is_correct:
                continue
        if not a.retested:
            return True  # 有未复练的错题 → 待复习
        # 已复练：按遗忘曲线算下次到期
        base = _as_aware(a.retested_at) or _as_aware(a.created_at) or datetime.now(timezone.utc)
        interval = min(2 ** int(getattr(a, "review_count", 0) or 0), 30)
        due = base + timedelta(days=interval)
        if due.date() <= today:
            return True
    return False


def build_prereq_chain(chapters: list) -> dict[int, str]:
    """前置依赖：章节顺序为链（ch_i 的前置是 ch_{i-1}）。返回 {chapter_index: 前置标题}。"""
    prereq = {}
    for i, ch in enumerate(chapters):
        if i > 0:
            prereq[i] = (chapters[i - 1].get("title") if isinstance(chapters[i - 1], dict)
                         else getattr(chapters[i - 1], "title", "")) or f"第{i}章"
    return prereq


def diagnose(script, analytics_rows: list, review_mode: str = "smart") -> dict:
    """生成学情诊断与推荐。script：Script 对象（chapters）。analytics_rows：该剧本作答记录。

    返回结构与 schemas.DiagnosisOut 一致。
    """
    chapters = script.chapters
    now = datetime.now(timezone.utc)
    today = _today()
    prereq = build_prereq_chain(chapters)

    rows_by_ch: dict[int, list] = {}
    for a in analytics_rows:
        rows_by_ch.setdefault(a.chapter_index, []).append(a)

    total_ms = sum(int(a.time_cost or 0) for a in analytics_rows)
    total_study_minutes = round(total_ms / 60000.0, 1)
    active_days = len({(a.created_at or now).date() for a in analytics_rows if a.created_at})

    points = []
    for i, ch in enumerate(chapters):
        title = ch.get("title") if isinstance(ch, dict) else getattr(ch, "title", "")
        rows = rows_by_ch.get(i, [])
        covered = bool(rows)
        mastery = compute_mastery(rows) if rows else 0.0
        has_due = chapter_has_due(rows, today) if rows else False
        review_count = max((int(getattr(a, "review_count", 0) or 0) for a in rows), default=0)
        next_due = ""
        if rows:
            # 取该章错题最新 retested_at 的下次日期
            wrong = [a for a in rows if not a.is_correct]
            if wrong:
                latest = max((_as_aware(a.retested_at) or _as_aware(a.created_at) or now for a in wrong), default=None)
                rc = max(int(getattr(a, "review_count", 0) or 0) for a in wrong)
                inter = min(2 ** rc, 30)
                next_due = (latest + timedelta(days=inter)).isoformat()[:10] if latest else today.isoformat()

        pre_title = prereq.get(i, "")
        pre_weak = False
        if pre_title:
            pre_ch = i - 1
            pre_rows = rows_by_ch.get(pre_ch, [])
            pre_covered = bool(pre_rows)
            pre_mastery = compute_mastery(pre_rows) if pre_rows else 0.0
            pre_weak = (not pre_covered) or (pre_mastery < WEAK_THRESHOLD)

        # 状态与动作
        if has_due:
            status = "due"
            action = "今日复习（遗忘曲线到期）"
        elif not covered:
            status = "untouched"
            action = "去学习该知识点"
        elif mastery < WEAK_THRESHOLD:
            status = "weak"
            action = f"巩固薄弱（掌握度 {int(mastery * 100)}%）"
        else:
            status = "ok"
            action = "已掌握，可轮换巩固"

        needs_prereq = bool(pre_title) and pre_weak and not has_due
        if needs_prereq:
            action += f"；建议先补前置：{pre_title}"

        points.append({
            "chapter_index": i,
            "title": title,
            "mastery": mastery,
            "covered": covered,
            "status": status,
            "review_count": review_count,
            "next_due": next_due,
            "prerequisite_of": pre_title,
            "needs_prereq": needs_prereq,
            "recommended_action": action,
        })

    # 推荐优先级：due → 未作答 → 薄弱 → 其余，按 chapter 序稳定
    def rank(p):
        order = {"due": 0, "untouched": 1, "weak": 2, "ok": 3}
        return order.get(p["status"], 4)

    if review_mode == "naive":
        priority = [p["chapter_index"] for p in points]          # 普通复习：按章节顺序
    else:
        priority = [p["chapter_index"] for p in sorted(points, key=lambda p: (rank(p), p["chapter_index"]))]

    return {
        "script_id": script.id,
        "script_title": script.title,
        "review_mode": review_mode,
        "total_study_minutes": total_study_minutes,
        "active_days": active_days,
        "next_review_priority": priority,
        "points": points,
    }
