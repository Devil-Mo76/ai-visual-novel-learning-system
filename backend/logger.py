"""Loguru 结构化日志配置。

约定：
- 日志文件按日期切分（每日零点滚动）：backend/logs/app_{YYYY-MM-DD}.log。
- 终端（stderr）保留 INFO 级「临时日志」，单次使用实时可见（演示/现场排查用）。
- 通过 InterceptHandler 接管 stdlib logging，让各 router/service 的 logger
  统一汇入 Loguru 的两个 sink，保证「一次记录、文件与终端都可见」。
- AI 调用（chat / stream_chat）由 script_engine 记录耗时 / 输入 token / 输出 token，
  异常时记录完整堆栈。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

from .config import settings


class InterceptHandler(logging.Handler):
    """把 stdlib logging 记录转发到 Loguru，保留异常堆栈信息。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and Path(frame.f_code.co_filename).name == Path(logging.__file__).name:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _desensitize_filter(record) -> bool:
    """日志脱敏：把日志里可能出现的 api_key/password/token=... 掩码（安全加固 B4）。"""
    import re

    msg = record.get("message") or ""
    msg = re.sub(
        r"(api_key|password|token)['\"]?\s*[:=]\s*['\"][^'\"]*['\"]",
        r"\1=***",
        msg,
    )
    record["message"] = msg
    return True


def setup_logging() -> None:
    """配置 Loguru：移除默认 sink，注册 终端 + 按日切分文件 两个 sink，并接管 stdlib。"""
    logger.remove()  # 去掉 Loguru 自身默认 stderr sink，避免与下方终端 sink 重复

    # 1) 终端临时日志（INFO 起，实时可见，用于单次使用记录）
    #    先确保 sys.stderr 以 UTF-8 输出（Windows 默认可能是 GBK），
    #    配合终端 chcp 65001，保证中文在终端/转发管道都不乱码。
    #    注：loguru 的 encoding 参数仅对「路径字符串」sink 生效，传给 file-like
    #    (sys.stderr) 会抛 TypeError，故改在 stderr 流自身 reconfigure。
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 非 TextIOWrapper（如无 stderr）时忽略
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
        colorize=True,
        backtrace=False,
        diagnose=False,
        filter=_desensitize_filter,     # 日志脱敏
    )

    # 2) 按日期切分的文件日志（backend/logs/app_YYYY-MM-DD.log）
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "app_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",          # 每天零点按日期切分
        retention="30 days",       # 保留 30 天
        encoding="utf-8",
        enqueue=True,              # 线程安全（后台线程池同样会写日志）
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}",
        backtrace=True,
        diagnose=True,
        filter=_desensitize_filter,     # 日志脱敏
    )

    # 3) 接管 stdlib logging（各 router/service 的 logging.getLogger 统一汇入 Loguru）
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)


def get_logger() -> logger:
    return logger