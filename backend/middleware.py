"""统一中间件：指标采集 + 限流/防刷（网络工程强化）。

- MetricsMiddleware：纯 ASGI，首包响应即记录 method/路径组/status/耗时进 metrics。
- RateLimitMiddleware：对生成 / 讲师 / 登录 等昂贵或敏感端点按用户令牌桶限流（429）。

用纯 ASGI（而非 BaseHTTPMiddleware），避免对 SSE(讲师流式) 造成阻塞/行为改变。
路径组归一化：/api/首两段（如 api/scripts、api/lecture），避免高基数。
"""

from __future__ import annotations

import hashlib
import time

from .services import metrics as metrics_svc
from .services import ratelimit

# 限流规则：匹配（子串, 限流器）
_RATE_RULES: list[tuple[str, object]] = [
    ("/api/auth/login", ratelimit.login_limiter),
    ("/api/auth/register", ratelimit.login_limiter),
    ("/api/scripts/generate", ratelimit.generate_limiter),
    ("/api/lecture/chat", ratelimit.lecture_limiter),
]


def normalize_group(path: str) -> str:
    """/api/[router]（再取下一段作子类）→ 'api/scripts/generate'。"""
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        head = "/".join(parts[:3]) if len(parts) >= 3 else "/".join(parts[:2])
        return head
    return "/".join(parts[:2]) if parts else "/"


def _client_key(scope) -> str:
    """限流键：优先按 Authorization token 的哈希（区分用户），无 token 按 client IP。"""
    for k in ("authorization", "Authorization"):
        val = [v for v in scope.get("headers", []) if v[0].decode("latin1").lower() == k.lower()]
        if val:
            token = val[0][1].decode("latin1")
            return "u:" + hashlib.sha256(token.encode()).hexdigest()[:16]
    client = scope.get("client")
    return "ip:" + (str(client[0]) if client else "anon")


class MetricsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        group = normalize_group(scope.get("path", ""))
        method = scope.get("method", "GET")
        recorded = False

        async def send_wrapper(message):
            nonlocal recorded
            if message["type"] == "http.response.start" and not recorded:
                recorded = True
                metrics_svc.metrics.record(method, group, message.get("status", 200), time.perf_counter() - start)
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limiter = None
        rule = ""
        for sub, l in _RATE_RULES:
            if sub in path:
                limiter, rule = l, sub
                break
        if limiter:
            key = _client_key(scope)
            if not limiter.allow(key):
                wait = max(1, int(limiter.retry_after(key)) + 1)
                body = ('{"detail":"请求过于频繁，请 %d 秒后再试。","error_code":"RATE_LIMITED"}' % wait).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(wait).encode("latin1")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
