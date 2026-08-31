"""异步任务队列（进程内线程池，零额外依赖）。

用途：把剧本生成等耗时操作丢到后台线程池执行，接口立即返回 task_id，
前端通过 GET /api/tasks/{task_id}/status 轮询进度与结果。

任务状态机：
  PENDING → PROGRESS → SUCCESS
                     ↘ FAILED

进度回调约定：worker 函数签名固定为
  def worker(on_progress: Callable[[int, str], None], *args) -> Any

说明：任务表与结果保存在进程内内存，进程重启后任务丢失（生成剧本为一次性
操作，可接受）。若后续需要跨进程/断点续跑，可平滑替换为 RQ/Celery + Redis。
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

# ── 任务注册表（进程内内存）──
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()

# ── 线程池：2 个并发 worker，足够单机演示（生成剧本耗时长，避免挤爆线程）──
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vn-task")


def create_task(worker: Callable, *args, **kwargs) -> str:
    """提交后台任务，立即返回 task_id。

    worker 签名必须是 `worker(on_progress, *args, **kwargs)`。
    """
    task_id = str(uuid.uuid4())
    with _LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "status": "PENDING",
            "progress": 0,
            "message": "任务已创建，等待执行…",
            "result": None,
            "error": None,
        }

    def on_progress(percent: int, message: str) -> None:
        update_progress(task_id, percent, message)

    _EXECUTOR.submit(_run, task_id, worker, args, kwargs, on_progress)
    return task_id


def get_task(task_id: str) -> dict | None:
    """读取任务快照（外部只读，返回副本防串改）。"""
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


def update_progress(task_id: str, percent: int, message: str) -> None:
    """更新任务进度（线程安全）。"""
    percent = max(0, min(100, int(percent)))
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        task["status"] = "PROGRESS"
        task["progress"] = percent
        task["message"] = message


def _run(task_id: str, worker: Callable, args: tuple, kwargs: dict, on_progress: Callable) -> None:
    try:
        if on_progress:
            on_progress(5, "任务已开始执行…")
        result = worker(on_progress, *args, **kwargs)
        with _LOCK:
            task = _TASKS.get(task_id)
            if task:
                task["status"] = "SUCCESS"
                task["progress"] = 100
                task["message"] = "任务执行完成。"
                task["result"] = result
    except Exception as exc:  # 后台异常：标记 FAILED 并保留错误信息
        with _LOCK:
            task = _TASKS.get(task_id)
            if task:
                task["status"] = "FAILED"
                task["error"] = str(exc)
                task["message"] = f"任务执行失败：{exc}"