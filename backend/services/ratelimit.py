"""轻量进程内令牌桶限流（防刷 / 防滥用，网络安全加固）。

按 key（user_id 或 IP）为每个端点维护令牌桶，供生成/讲师/登录等昂贵或敏感接口限流。
- 生成剧本 generate：10 次/分（单用户交互/演示足够，仍防脚本刷爆云端额度）
- 讲师问答 lecture/chat：20 次/分
- 登录/注册 auth/login|register：5 次/分

线程安全。单实例进程内限流；如需分布式可扩展为 Redis（注释说明，本轮不扩）。
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """按 key 的令牌桶（滑动补令牌，容量封顶）。"""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._ts: dict[str, float] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            tokens = self._tokens.get(key)
            ts = self._ts.get(key, now)
            if tokens is None:
                self._tokens[key] = float(self.capacity - 1)
                self._ts[key] = now
                return True
            # 按时间补令牌
            elapsed = now - ts
            tokens = min(float(self.capacity), tokens + elapsed * self.refill)
            if tokens >= 1.0:
                self._tokens[key] = tokens - 1.0
                self._ts[key] = now
                return True
            self._tokens[key] = tokens
            self._ts[key] = now
            return False

    def retry_after(self, key: str, now: float | None = None) -> float:
        """距下一枚令牌可用还需多少秒（用于 429 的 Retry-After 提示）。"""
        if self.refill <= 0:
            return 60.0
        now = now if now is not None else time.time()
        with self._lock:
            tokens = self._tokens.get(key, 0.0)
            ts = self._ts.get(key, now)
            tokens = min(float(self.capacity), tokens + (now - ts) * self.refill)
        deficit = max(0.0, 1.0 - tokens)
        return deficit / self.refill


# —— 各端点限流实例（容量 / 每秒补速）——
# 60 秒内约 N 次：refill = N / 60
login_limiter = TokenBucket(5, 5 / 60.0)       # 登录/注册 5 次/分
generate_limiter = TokenBucket(10, 10 / 60.0)  # 生成剧本 10 次/分
lecture_limiter = TokenBucket(20, 20 / 60.0)   # 讲师问答 20 次/分


def client_key(db=None, identity: str = "") -> str:
    """限流键：优先用传入的 identity（如 user_id），否则退化为 IP 占位。"""
    if identity:
        return identity
    return "anonymous"
