"""轻量进程内 Prometheus 风格指标采集（无第三方依赖）。

供「网络化部署 + 可观测性」使用：/api/metrics 以 Prometheus 文本格式输出，
Prometheus 可直接抓取，Grafana 可视化 QPS / 延迟分位 / 错误率 / AI 调用数。

指标：
- requests_total      {method, path_group, status}  请求计数
- requests_error_total {path_group}                  4xx/5xx 计数
- request_duration_seconds   直方图桶                请求耗时
- ai_calls_total       {kind}                        外部 AI 调用计数（生成/判题/讲师）
- ai_call_duration_seconds   直方图桶                外部 AI 调用耗时

线程安全（锁）。path_group 由 main.py 归一化（按 /api/首段），避免高基数。
"""
from __future__ import annotations

import threading

# Prometheus 直方图桶（秒）：覆盖从快到慢的常见请求耗时
_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = {}
        self._request_durations: list[tuple[str, float]] = []
        self._errors: dict[str, int] = {}
        self._ai_calls: dict[str, int] = {}
        self._ai_durations: dict[str, list[float]] = {}

    # —— 记录 ——
    def record(self, method: str, path_group: str, status: int, duration: float) -> None:
        with self._lock:
            self._requests[(method, path_group, status)] = self._requests.get((method, path_group, status), 0) + 1
            self._request_durations.append((path_group, duration))
            if status >= 400:
                self._errors[path_group] = self._errors.get(path_group, 0) + 1

    def record_ai(self, kind: str, duration: float) -> None:
        with self._lock:
            self._ai_calls[kind] = self._ai_calls.get(kind, 0) + 1
            self._ai_durations.setdefault(kind, []).append(duration)

    # —— Prometheus 文本输出 ——
    def render_text(self) -> str:
        lines: list[str] = []
        with self._lock:
            # 请求计数
            lines.append("# HELP requests_total HTTP 请求计数")
            lines.append("# TYPE requests_total counter")
            for (method, group, status), n in sorted(self._requests.items()):
                lines.append(f'requests_total{{method="{method}",path_group="{group}",status="{status}"}} {n}')
            if not self._requests:
                lines.append('requests_total{method="GET",path_group="api/",status="200"} 0')

            # 错误计数
            lines.append("# HELP requests_error_total HTTP 错误(4xx/5xx)计数")
            lines.append("# TYPE requests_error_total counter")
            for group, n in sorted(self._errors.items()):
                lines.append(f'requests_error_total{{path_group="{group}"}} {n}')
            if not self._errors:
                lines.append('requests_error_total{path_group="api/"} 0')

            # 请求耗时直方图
            lines.extend(self._histogram_text("request_duration_seconds", self._request_durations, "请求耗时(秒)"))

            # AI 调用计数
            lines.append("# HELP ai_calls_total 外部 AI 调用计数")
            lines.append("# TYPE ai_calls_total counter")
            for kind, n in sorted(self._ai_calls.items()):
                lines.append(f'ai_calls_total{{kind="{kind}"}} {n}')
            if not self._ai_calls:
                lines.append('ai_calls_total{kind="none"} 0')

            # AI 调用耗时时直方图（按 kind）
            for kind, dur in sorted(self._ai_durations.items()):
                lines.append(f"# HELP ai_call_duration_seconds 外部 AI 调用耗时({kind})")
                lines.append("# TYPE ai_call_duration_seconds histogram")
                lines.extend(self._histogram_series(f'ai_call_duration_seconds{{kind="{kind}"}}', dur, "秒"))

        return "\n".join(lines) + "\n"

    # —— 内部直方图文本（所有 path_group 合并计算桶）——
    def _histogram_text(self, name: str, samples: list[tuple[str, float]], help_text: str) -> list[str]:
        out: list[str] = [f"# HELP {name} {help_text}", f"# TYPE {name} histogram"]
        return out + self._histogram_series(name, [s[1] for s in samples], "秒")

    def _histogram_series(self, name: str, samples: list[float], unit: str) -> list[str]:
        if not samples:
            return [f'{name}_bucket{{le="{_BUCKETS[0]}"}} 0', f'{name}_count 0', f'{name}_sum 0']
        total = len(samples)
        total_seconds = sum(samples)
        out: list[str] = []
        cum = 0
        for b in _BUCKETS:
            cum = sum(1 for s in samples if s <= b)
            out.append(f'{name}_bucket{{le="{b}"}} {cum}')
        out.append(f'{name}_bucket{{le="+Inf"}} {total}')
        out.append(f"{name}_count {total}")
        out.append(f"{name}_sum {total_seconds}")
        return out


# 全局单例（进程内一个实例即可）
metrics = Metrics()
