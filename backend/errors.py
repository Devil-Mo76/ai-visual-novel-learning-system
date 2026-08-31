"""统一错误响应：{"detail": "...", "error_code": "..."}。

- ApiError：带 error_code 的业务错误（AI 超时、生成失败、缺少 Key 等）。
- FastAPI 全局异常处理器：把 HTTPException 与未捕获异常统一转为
  {"detail", "error_code"} JSON，前端据此映射友好提示。
  HTTPException 若无显式 error_code，则按 status_code 取默认码（DEFAULT_CODE_BY_STATUS）。
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .logger import get_logger

logger = get_logger()

# —— 常用 AI 错误码 ——
AI_TIMEOUT = "AI_TIMEOUT"                     # AI 调用超时
AI_GENERATE_FAILED = "AI_GENERATE_FAILED"     # 剧本生成连续失败
AI_KEY_MISSING = "AI_KEY_MISSING"             # 未配置 API Key

# —— 按 HTTP 状态码取默认 error_code ——
DEFAULT_CODE_BY_STATUS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
}


class ApiError(HTTPException):
    """业务错误：status_code + detail(给用户看) + error_code(前端映射)。"""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code or DEFAULT_CODE_BY_STATUS.get(status_code, "INTERNAL_ERROR")


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """统一 HTTPException → {"detail", "error_code"}。"""
    code = getattr(exc, "error_code", None)
    if not code:
        code = DEFAULT_CODE_BY_STATUS.get(exc.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail), "error_code": code},
    )


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常：记录完整堆栈，统一返回 500 格式。"""
    logger.opt(exception=exc).error(
        "未处理异常 | {} {} | {}",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试。", "error_code": "INTERNAL_ERROR"},
    )