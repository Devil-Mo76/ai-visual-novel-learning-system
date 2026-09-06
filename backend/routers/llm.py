"""模型路由接口（云端-边缘混合降级的可观测入口）。

- GET  /api/llm/status   路由状态全貌：策略、两引擎可用性、云端熔断态、调用统计
- POST /api/llm/probe    主动探测两引擎（本地加载检查 + 云端链路探测 + 实测延迟）
- POST /api/llm/engine   切换路由策略（auto/local/cloud，落库 settings.llm_engine）
- POST /api/llm/test     单次连通性自测（可指定引擎跑一句话）
- POST /api/llm/bench    判题基准测试：本地 vs 云端同题对比，产出论文指标

设计要点：
- 这些接口只做「观测与控制」，不参与业务链路，失败也不影响学习主流程。
- bench 会真实调用模型（本地推理 + 云端计费调用），故限流保护，避免误触刷爆额度。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Settings, User
from ..schemas import LlmBenchIn, LlmBenchOut, LlmEngineIn, LlmTestIn, LlmTestOut
from ..services import llm
from ..services.metrics import metrics
from ..services.ratelimit import TokenBucket

logger = logging.getLogger("llm_router_api")
router = APIRouter(prefix="/api/llm", tags=["llm"])

# 基准测试要真调模型（云端计费），限流防误触：3 次/分
_bench_limiter = TokenBucket(3, 3 / 60.0)
_test_limiter = TokenBucket(20, 20 / 60.0)

_EVAL_CASES = Path(__file__).resolve().parent.parent / "eval" / "grading_cases.json"


def _api_config(db: Session) -> tuple[str, str, str, str, str]:
    """(api_base, api_key, model, llm_engine, thinking_level)"""
    row = db.get(Settings, 1)
    if row is None:
        return "https://api.deepseek.com", "", "deepseek-v4-flash", "auto", "high"
    return (
        row.api_base or "https://api.deepseek.com",
        row.api_key or "",
        row.model or "deepseek-v4-flash",
        (getattr(row, "llm_engine", "") or "auto"),
        (getattr(row, "thinking_level", None) or "high"),
    )


def _sync_runtime_engine(db: Session) -> str:
    """把数据库里的策略同步到路由层（每次请求前调用，保证设置即时生效）。"""
    _, _, _, engine, _ = _api_config(db)
    llm.set_runtime_engine(engine if engine in ("auto", "local", "cloud") else None)
    return llm.engine_choice()


# ---------- 状态 ----------

@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """路由层状态全貌（前端「模型引擎」面板直接消费这个接口）。"""
    api_base, api_key, model, engine_db, thinking_level = _api_config(db)
    llm.set_runtime_engine(engine_db if engine_db in ("auto", "local", "cloud") else None)
    return llm.status(api_base=api_base, api_key=api_key, model=model)


# ---------- 探测 ----------

@router.post("/probe")
def probe(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """主动探测两个引擎：本地能否加载 + 云端链路是否可达，并给出实测延迟。

    本地探测会真实加载模型（首次约数秒）；云端探测只发 GET /models，不产生计费。
    """
    api_base, api_key, model, engine_db, thinking_level = _api_config(db)
    _sync_runtime_engine(db)

    # —— 本地：加载 + 跑一句极短生成，量出真实首字延迟 ——
    local_info: dict = {"available": False, "load_error": "", "latency_ms": 0, "sample": ""}
    if llm.local_available():
        local_info["available"] = True
        t0 = time.perf_counter()
        try:
            out = llm.route_chat(
                api_base=api_base, api_key=api_key, model=model,
                system="你是一个简洁的助手，只回答一句话。",
                user="说“本地模型就绪”五个字。",
                task="short", max_tokens=32, timeout=60, engine="local",
            )
            local_info["latency_ms"] = out.latency_ms
            local_info["sample"] = out.text[:80]
        except Exception as exc:
            local_info["load_error"] = str(exc)[:200]
    else:
        local_info["load_error"] = llm.local_engine().load_error()

    # —— 云端：链路探测（GET /models，不计费） ——
    cloud_info = llm.probe_cloud(api_base, api_key)
    cloud_info["circuit"] = llm.cloud_health().snapshot()

    return {
        "engine_choice": llm.engine_choice(),
        "local": local_info,
        "cloud": cloud_info,
        "effective": {
            "short": llm.resolve_engine("short", api_key),
            "long": llm.resolve_engine("long", api_key),
        },
    }


# ---------- 切换策略 ----------

@router.post("/engine")
def switch_engine(payload: LlmEngineIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """切换模型路由策略并落库。

    auto  —— 短任务本地优先、长任务云端优先（默认，推荐）
    local —— 强制本地 Qwen（完全离线，答辩断网演示用）
    cloud —— 强制云端 DeepSeek（追求生成质量）
    """
    engine = (payload.engine or "auto").strip().lower()
    if engine not in ("auto", "local", "cloud"):
        raise HTTPException(400, "engine 只能是 auto / local / cloud")
    if engine == "local" and not llm.local_available():
        raise HTTPException(400, f"本地模型不可用：{llm.local_engine().load_error() or '未安装'}")

    row = db.get(Settings, 1)
    if row is None:
        row = Settings(id=1)
        db.add(row)
    row.llm_engine = engine
    db.commit()
    llm.set_runtime_engine(engine)
    logger.info("模型路由策略切换为 %s（user_id=%d）", engine, user.id)

    api_base, api_key, model, _, thinking_level = _api_config(db)
    return {
        "engine": engine,
        "effective": {
            "short": llm.resolve_engine("short", api_key),
            "long": llm.resolve_engine("long", api_key),
        },
    }


# ---------- 单次自测 ----------

@router.post("/test", response_model=LlmTestOut)
def test_route(payload: LlmTestIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """用指定引擎跑一句话，返回文本与延迟（设置界面的「测一下」按钮）。"""
    if not _test_limiter.allow(f"test:{user.id}"):
        raise HTTPException(429, "自测过于频繁，请稍后再试（限 20 次/分钟）。")
    api_base, api_key, model, _, thinking_level = _api_config(db)
    _sync_runtime_engine(db)
    task = "long" if payload.task == "long" else "short"

    t0 = time.perf_counter()
    try:
        res = llm.route_chat(
            api_base=api_base, api_key=api_key, model=model,
            system="你是一个简洁的助手。", user=payload.prompt,
            task=task, max_tokens=256, timeout=120,
            engine=payload.engine if payload.engine in ("auto", "local", "cloud") else None,
        )
        return LlmTestOut(
            success=True, engine=res.engine, task=task, model=res.model,
            text=res.text[:500], latency_ms=res.latency_ms, degraded=res.degraded,
        )
    except Exception as exc:
        return LlmTestOut(
            success=False, engine="", task=task,
            error=str(exc)[:300], latency_ms=int((time.perf_counter() - t0) * 1000),
        )


# ---------- 判题基准测试 ----------

def _load_cases(limit: int = 0) -> list[dict]:
    if not _EVAL_CASES.exists():
        return []
    data = json.loads(_EVAL_CASES.read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    return cases[:limit] if limit and limit > 0 else cases


@router.post("/bench", response_model=LlmBenchOut)
def bench(payload: LlmBenchIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """判题基准测试：同一批题目分别交给本地与云端，对比准确率、延迟与一致率。

    这是论文「按任务给真实指标」的数据来源——用实测数字说话，而不是拍脑袋的 85%。
    会真实调用云端 API（产生少量计费），故限流 3 次/分钟。
    """
    if not _bench_limiter.allow(f"bench:{user.id}"):
        raise HTTPException(429, "基准测试调用过于频繁，请稍后再试（限 3 次/分钟）。")

    api_base, api_key, model, _, thinking_level = _api_config(db)
    _sync_runtime_engine(db)

    cases = _load_cases(payload.limit)
    if not cases:
        raise HTTPException(404, f"评测集为空或不存在：{_EVAL_CASES}")

    wanted = [e.strip() for e in (payload.engines or "local,cloud").split(",") if e.strip()]
    # 引擎可用性预检：不可用的直接跳过并在 note 里说明，避免刷屏报错
    usable = []
    for eng in wanted:
        if eng == "local" and not llm.local_available():
            continue
        if eng == "cloud" and not api_key:
            continue
        usable.append(eng)
    if not usable:
        raise HTTPException(400, "当前没有可用的引擎参与评测（本地模型未装，且未配置 API Key）。")

    from ..services.script_engine import judge_answer

    results: dict[str, dict] = {e: {"verdicts": {}, "latencies": []} for e in usable}
    for case in cases:
        for eng in usable:
            t0 = time.perf_counter()
            try:
                out = judge_answer(
                    api_base, api_key, model,
                    question=case["question"],
                    reference=case["reference"],
                    answer=case["answer"],
                    source=case.get("source", ""),
                    engine=eng,
                    reasoning_effort=thinking_level,
                )
                verdict = bool(out.get("correct"))
                engine_name = out.get("engine", eng)
            except Exception as exc:
                verdict = None
                engine_name = eng
                logger.warning("bench %s 在 %s 上判题失败：%s", case["id"], eng, exc)
            results[eng]["verdicts"][case["id"]] = verdict
            results[eng]["latencies"].append(int((time.perf_counter() - t0) * 1000))
            results[eng].setdefault("engine_name", engine_name)

    # —— 汇总指标 ——
    engine_report: dict = {}
    for eng, data in results.items():
        lat = sorted(data["latencies"])
        n = len(lat)
        hit = sum(1 for c in cases if data["verdicts"].get(c["id"]) is True and c["expected"] is True)
        wrong_pass = sum(1 for c in cases if data["verdicts"].get(c["id"]) is False and c["expected"] is False)
        judged = sum(1 for c in cases if data["verdicts"].get(c["id"]) is not None)
        total_expected_true = sum(1 for c in cases if c["expected"] is True)
        total_expected_false = sum(1 for c in cases if c["expected"] is False)

        def pct(p: float) -> int:
            return lat[min(n - 1, max(0, int(round(p / 100 * (n - 1)))))] if n else 0

        engine_report[eng] = {
            "accuracy": round((hit + wrong_pass) / judged * 100, 1) if judged else 0.0,
            "judged": judged,
            "recall_on_correct": round(hit / total_expected_true * 100, 1) if total_expected_true else 0.0,
            "specificity_on_wrong": round(wrong_pass / total_expected_false * 100, 1) if total_expected_false else 0.0,
            "avg_latency_ms": round(sum(lat) / n) if n else 0,
            "p50_latency_ms": pct(50),
            "p95_latency_ms": pct(95),
            "min_latency_ms": lat[0] if n else 0,
            "max_latency_ms": lat[-1] if n else 0,
            "model": data.get("engine_name", eng),
        }

    # —— 两引擎一致率（都跑成功才有意义）——
    agreement = None
    if len(usable) >= 2:
        a, b = usable[0], usable[1]
        both = [c for c in cases
                if results[a]["verdicts"].get(c["id"]) is not None
                and results[b]["verdicts"].get(c["id"]) is not None]
        if both:
            same = sum(1 for c in both
                       if results[a]["verdicts"][c["id"]] == results[b]["verdicts"][c["id"]])
            agreement = round(same / len(both) * 100, 1)

    skipped = [e for e in wanted if e not in usable]
    note = f"评测集 {len(cases)} 题（操作系统基础）。"
    if skipped:
        note += f" 跳过不可用引擎：{'、'.join(skipped)}。"
    note += " 准确率 = 与人工标注一致的判定占比（含正确判定为对、错误判定为错）。"

    metrics.record_ai("bench", 0)
    return LlmBenchOut(
        total_cases=len(cases),
        engines=engine_report,
        agreement=agreement,
        cases=[
            {
                "id": c["id"],
                "note": c.get("note", ""),
                "expected": c["expected"],
                **{f"{eng}_verdict": results[eng]["verdicts"].get(c["id"]) for eng in usable},
            }
            for c in cases
        ],
        note=note,
    )
