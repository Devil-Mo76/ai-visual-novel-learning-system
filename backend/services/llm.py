"""云端-边缘混合路由层（Cloud-Edge Hybrid Routing）。

把「调用哪个模型」这件事从业务代码里彻底剥离出来，由本模块按**任务类型**与
**实时网络状况**自动决策，形成论文中的「边缘离线降级 + 网络自适应路由」：

    任务进来 ──┬─ 短任务（判题 / 质量评估 / 目标匹配 / 讲师短答）
              │     └─ 本地 Qwen2.5-1.5B 优先（离线、低延迟、零流量）
              │          └─ 本地不可用 → 云端 DeepSeek（自动降级）
              │
              └─ 长任务（生成剧本）
                    └─ 云端 DeepSeek 优先（生成质量）
                         └─ 网络不可用 / 超时 → 抛 RouteError
                              → 由上层 P1「离线样例剧本」兜底

【网络自适应】云端可用性由 CloudHealth 熔断器持续跟踪：
  closed（正常） --连续失败N次--> open（降级到本地）
       ^                              |
       |--- 冷却期后探测成功（回切）---┘  half_open（半开探测一次）
可选后台看门狗线程（ROUTE_WATCHDOG=1）周期性探测云端，断网恢复后自动回切。

【配置开关】（backend/.env 或项目根 .env）
  LLM_ENGINE        = auto（默认）| local（强制本地）| cloud（强制云端）
  LOCAL_MODEL_PATH  = 本地 GGUF 路径（默认 项目根/models/qwen2.5-1.5b-instruct-q4_k_m.gguf）
  LOCAL_NCTX / LOCAL_NTHREADS / LOCAL_GPU_LAYERS / LOCAL_PRELOAD
  ROUTE_FAIL_THRESHOLD / ROUTE_COOLDOWN_SEC / ROUTE_PROBE_TIMEOUT / ROUTE_WATCHDOG

【设计约束】
- 本地引擎 llama-cpp-python 进程内推理，**不发起任何外部 HTTP 请求**（离线可用）。
- 未安装 llama-cpp-python 或模型文件缺失 → 本地引擎视为不可用，静默降级云端。
- 本模块不依赖 fastapi/sqlalchemy，可单独 import 做离线自测。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger("llm_router")

# backend/services/ 上溯两级 = 项目根（frontend/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"

ENGINE_LOCAL = "local"
ENGINE_CLOUD = "cloud"

# 任务画像：短任务本地优先（延迟敏感、输出短），长任务云端优先（质量敏感、输出长）
SHORT_TASKS = {"short", "grade", "eval", "lecture", "chat", "mastery", "summary"}
LONG_TASKS = {"long", "generate", "script"}

_DEFAULT_GGUF = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


# ══════════════════════════════════════════════════════════════
# 一、配置读取（.env → os.environ，真实环境变量优先级更高）
# ══════════════════════════════════════════════════════════════

_ENV_LOADED = False
_ENV_LOCK = threading.Lock()


def _ensure_env_loaded() -> None:
    """把 .env 里的键值补进 os.environ（不覆盖已存在的真实环境变量）。

    为什么自己解析而不用 python-dotenv：pydantic-settings 只会把 .env 读进
    Settings 对象，不会写回 os.environ，导致本模块的 os.environ 读不到配置。
    这里做一个零依赖的极简解析，保证 llm.py 可独立运行/自测。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    with _ENV_LOCK:
        if _ENV_LOADED:
            return
        for path in (_BACKEND_DIR / ".env", _PROJECT_ROOT / ".env"):
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception as exc:  # .env 解析失败不应影响启动
                logger.debug("读取 %s 失败：%s", path, exc)
        _ENV_LOADED = True


def _env_str(name: str, default: str = "") -> str:
    _ensure_env_loaded()
    val = os.environ.get(name, "").strip()
    return val if val else default


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_str(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# 运行期策略覆盖（由数据库 settings.llm_engine 驱动，None = 交回 .env）
_RUNTIME_ENGINE: Optional[str] = None


def set_runtime_engine(engine: Optional[str]) -> None:
    """运行期覆盖引擎策略（设置界面切换用）；传 None 表示回落到 .env 的 LLM_ENGINE。"""
    global _RUNTIME_ENGINE
    _RUNTIME_ENGINE = engine if engine in ("auto", "local", "cloud") else None


def engine_choice(override: Optional[str] = None) -> str:
    """当前引擎策略：auto（默认）| local | cloud。

    优先级：单次调用 override > 数据库运行期设置 > .env 的 LLM_ENGINE > auto。
    """
    val = (override or _RUNTIME_ENGINE or _env_str("LLM_ENGINE", "auto")).strip().lower()
    return val if val in ("auto", "local", "cloud") else "auto"


def model_path() -> str:
    """本地 GGUF 模型绝对路径。"""
    custom = _env_str("LOCAL_MODEL_PATH")
    if custom:
        return custom
    name = _env_str("LOCAL_MODEL", _DEFAULT_GGUF)
    return str(_PROJECT_ROOT / "models" / name)


# ══════════════════════════════════════════════════════════════
# 二、路由结果（一次调用的完整画像，供指标/论文数据采集）
# ══════════════════════════════════════════════════════════════


@dataclass
class RouteResult:
    """一次路由调用的完整结果。

    engine/latency_ms/first_token_ms/degraded 是论文「按任务给真实指标」的数据源：
    判题类短任务看 local 的延迟与一致性，生成类长任务看 cloud 的耗时与成功率。
    """

    text: str = ""
    engine: str = ""
    task: str = "short"
    model: str = ""
    latency_ms: int = 0          # 端到端耗时
    first_token_ms: int = 0      # 首字延迟（流式场景）
    ok: bool = True
    degraded: bool = False       # 是否从首选引擎降级而来
    fallback_from: str = ""      # 原首选引擎
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "task": self.task,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "first_token_ms": self.first_token_ms,
            "ok": self.ok,
            "degraded": self.degraded,
            "fallback_from": self.fallback_from,
            "error": self.error,
        }


@dataclass
class RouteCtx:
    """流式调用的上下文容器：流结束后可从 ctx.result 读到本次路由画像。"""

    result: Optional[RouteResult] = None


class RouteError(RuntimeError):
    """所有候选引擎均不可用（上层据此走 P1 样例剧本兜底）。"""


# ══════════════════════════════════════════════════════════════
# 三、云端健康跟踪（熔断器：降级 / 半开探测 / 回切）
# ══════════════════════════════════════════════════════════════


class CloudHealth:
    """云端链路健康状态机。

    closed    —— 正常，请求直发云端
    open      —— 已熔断（连续失败达阈值），请求改走本地
    half_open —— 冷却期已过，放行一次探测请求；成功则回切 closed，失败则重回 open

    这就是论文里的「网络自适应路由」：不需要人工干预，云端恢复后自动回切。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "closed"
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_success = 0
        self.last_error = ""
        self.last_failure_at = 0.0
        self.last_success_at = 0.0
        self.opened_at = 0.0
        self.degrade_count = 0     # 累计降级次数
        self.recovery_count = 0    # 累计回切次数

    # —— 阈值（每次读取，支持运行期改 .env 后重启生效）——
    @property
    def threshold(self) -> int:
        return max(1, _env_int("ROUTE_FAIL_THRESHOLD", 2))

    @property
    def cooldown(self) -> float:
        return max(5.0, _env_float("ROUTE_COOLDOWN_SEC", 60.0))

    def record_success(self) -> None:
        with self._lock:
            self.total_success += 1
            self.consecutive_failures = 0
            self.last_error = ""
            self.last_success_at = time.time()
            if self.state != "closed":
                self.state = "closed"
                self.recovery_count += 1
                logger.info("云端链路已恢复，路由回切 cloud（累计回切 %d 次）", self.recovery_count)

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.total_failures += 1
            self.consecutive_failures += 1
            self.last_error = str(error)[:300]
            self.last_failure_at = time.time()
            if self.consecutive_failures >= self.threshold and self.state != "open":
                self.state = "open"
                self.opened_at = time.time()
                self.degrade_count += 1
                logger.warning(
                    "云端连续失败 %d 次，熔断降级到 local（%s）", self.consecutive_failures, self.last_error
                )

    def allow(self) -> bool:
        """当前是否允许打云端。半开态放行一次探测。"""
        with self._lock:
            if self.state == "closed":
                return True
            if time.time() - self.opened_at >= self.cooldown:
                if self.state == "open":
                    self.state = "half_open"
                    logger.info("云端冷却期结束，进入半开探测态")
                return True
            return False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "healthy": self.state == "closed",
                "consecutive_failures": self.consecutive_failures,
                "total_success": self.total_success,
                "total_failures": self.total_failures,
                "degrade_count": self.degrade_count,
                "recovery_count": self.recovery_count,
                "last_error": self.last_error,
                "last_success_at": self.last_success_at or None,
                "last_failure_at": self.last_failure_at or None,
                "threshold": self.threshold,
                "cooldown_sec": self.cooldown,
            }


_cloud_health = CloudHealth()


def cloud_health() -> CloudHealth:
    return _cloud_health


# ══════════════════════════════════════════════════════════════
# 四、本地引擎（llama-cpp-python，进程内 GGUF 推理，零外部请求）
# ══════════════════════════════════════════════════════════════


class LocalEngine:
    """Qwen2.5-1.5B-Instruct GGUF 本地推理封装。

    懒加载：首次调用才把 ~1GB 权重读进内存（约 2~5 秒），之后常驻。
    线程安全：推理过程加锁串行化，避免多线程并发把 CPU 打满导致延迟飙升。
    """

    def __init__(self) -> None:
        self._llm: Any = None
        self._inited = False
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._load_error = ""
        self._load_seconds = 0.0

    # —— 可用性 ——
    def available(self) -> bool:
        return self._get() is not None

    def load_error(self) -> str:
        self._get()
        return self._load_error

    def _get(self) -> Any:
        if self._inited:
            return self._llm
        with self._lock:
            if self._inited:
                return self._llm
            self._inited = True
            path = model_path()
            if not os.path.exists(path):
                self._load_error = f"本地模型文件不存在：{path}"
                logger.info("本地引擎不可用：%s", self._load_error)
                return None
            try:
                from llama_cpp import Llama
            except Exception as exc:
                self._load_error = f"未安装 llama-cpp-python（{exc}）"
                logger.info("本地引擎不可用：%s", self._load_error)
                return None
            try:
                t0 = time.perf_counter()
                n_ctx = max(512, _env_int("LOCAL_NCTX", 8192))
                n_threads = _env_int("LOCAL_NTHREADS", 0) or min(8, max(1, os.cpu_count() or 4))
                n_gpu_layers = _env_int("LOCAL_GPU_LAYERS", 0)
                self._llm = Llama(
                    model_path=path,
                    n_ctx=n_ctx,
                    n_threads=n_threads,
                    n_gpu_layers=n_gpu_layers,
                    verbose=False,
                )
                self._load_seconds = time.perf_counter() - t0
                self._load_error = ""
                logger.info(
                    "本地模型加载完成：%s（%.1fs, ctx=%d, threads=%d）",
                    Path(path).name, self._load_seconds, n_ctx, n_threads,
                )
            except Exception as exc:
                self._load_error = f"本地模型加载失败：{exc}"
                self._llm = None
                logger.warning(self._load_error)
        return self._llm

    # —— 非流式 ——
    def chat(
        self,
        system: str,
        user: str,
        history: Optional[list[dict]] = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> str:
        llm = self._get()
        if llm is None:
            raise RuntimeError(self._load_error or "本地模型不可用")
        messages = self._build_messages(system, user, history)
        with self._infer_lock:
            try:
                out = llm.create_chat_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=["<|im_end|>", "<|endoftext|>"],
                )
                return (out["choices"][0]["message"].get("content") or "").strip()
            except Exception:
                # 少数 GGUF 未内置 chat template，回退手工拼 ChatML
                return self._raw_chat(llm, messages, max_tokens, temperature)

    # —— 流式 ——
    def stream(
        self,
        system: str,
        user: str,
        history: Optional[list[dict]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Iterator[str]:
        llm = self._get()
        if llm is None:
            raise RuntimeError(self._load_error or "本地模型不可用")
        messages = self._build_messages(system, user, history)
        with self._infer_lock:
            try:
                for chunk in llm.create_chat_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=["<|im_end|>", "<|endoftext|>"],
                    stream=True,
                ):
                    delta = chunk["choices"][0]["delta"].get("content") or ""
                    if delta:
                        yield delta
                return
            except Exception:
                pass
            # 回退：非流式一次性产出（保证功能可用，牺牲流式体验）
            yield self._raw_chat(llm, messages, max_tokens, temperature)

    # —— 内部：消息组装 & 裸 prompt 回退 ——
    @staticmethod
    def _build_messages(system: str, user: str, history: Optional[list[dict]]) -> list[dict]:
        msgs: list[dict] = []
        if system and system.strip():
            msgs.append({"role": "system", "content": system.strip()})
        for m in history or []:
            role = m.get("role", "user")
            if role in ("user", "assistant") and m.get("content"):
                msgs.append({"role": role, "content": m["content"]})
        msgs.append({"role": "user", "content": user})
        return msgs

    @staticmethod
    def _raw_chat(llm: Any, messages: list[dict], max_tokens: int, temperature: float) -> str:
        """手工拼 Qwen ChatML 后调底层 completion（create_chat_completion 不可用时的回退）。"""
        parts: list[str] = []
        for m in messages:
            parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        out = llm(
            "".join(parts),
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
        )
        return (out["choices"][0]["text"] or "").strip()

    def snapshot(self) -> dict:
        path = model_path()
        exists = os.path.exists(path)
        return {
            "engine": ENGINE_LOCAL,
            "installed": self.available(),
            "model_path": path,
            "model_file": Path(path).name if exists else "",
            "model_exists": exists,
            "model_size_mb": round(os.path.getsize(path) / 1024 / 1024, 1) if exists else 0,
            "load_error": self._load_error,
            "load_seconds": round(self._load_seconds, 2),
            "n_ctx": _env_int("LOCAL_NCTX", 8192),
            "n_threads": _env_int("LOCAL_NTHREADS", 0) or min(8, max(1, os.cpu_count() or 4)),
            "n_gpu_layers": _env_int("LOCAL_GPU_LAYERS", 0),
        }


_local_engine = LocalEngine()


def local_engine() -> LocalEngine:
    return _local_engine


def local_available() -> bool:
    """本地引擎是否可用（llama-cpp-python 已装 + 模型文件存在）。"""
    return _local_engine.available()


def local_chat(prompt: str, max_tokens: int = 512, temperature: float = 0.4) -> str:
    """兼容旧签名：无 system 的裸 prompt 调用。"""
    return _local_engine.chat(system="", user=prompt, max_tokens=max_tokens, temperature=temperature)


# ══════════════════════════════════════════════════════════════
# 五、云端引擎（OpenAI 兼容协议，requests 直连）
# ══════════════════════════════════════════════════════════════


def _cloud_messages(system: str, user: str, history: Optional[list[dict]]) -> list[dict]:
    msgs: list[dict] = []
    if system and system.strip():
        msgs.append({"role": "system", "content": system.strip()})
    for m in history or []:
        role = m.get("role", "user")
        if role in ("user", "assistant") and m.get("content"):
            msgs.append({"role": role, "content": m["content"]})
    msgs.append({"role": "user", "content": user})
    return msgs


def cloud_chat(
    api_base: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    history: Optional[list[dict]] = None,
    max_tokens: int = 512,
    timeout: int = 100,
    temperature: float = 0.4,
    reasoning_effort: Optional[str] = None,
) -> str:
    """云端非流式调用。失败时抛异常，由路由层负责熔断记账。"""
    import requests

    if not api_key:
        raise RuntimeError("未配置有效 API Key")
    body = {
        "model": model,
        "messages": _cloud_messages(system, user, history),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    resp = requests.post(
        f"{api_base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    try:
        resp.raise_for_status()
    except Exception:
        raise RuntimeError(f"云端调用失败（HTTP {resp.status_code}）：{resp.text[:300]}")
    data = resp.json()
    text = (data["choices"][0]["message"].get("content") or "").strip()
    if not text:
        # DeepSeek V4 思考模式下 max_tokens 是「思考+正文」总预算，思考过长会把
        # 预算占满，正文一个字未出就 finish_reason=length → content 为空。
        # 抛明确错误，让上层据此放大预算/调低思考强度后重试，避免把空当成功。
        fin = data["choices"][0].get("finish_reason")
        if fin == "length":
            raise RuntimeError(
                "模型输出被 max_tokens 截断（思考占满预算，正文为空）。"
                "请调低思考强度或增大 max_tokens 后重试。"
            )
        raise RuntimeError("云端返回了空内容（content 为空）。")
    return text


def cloud_stream(
    api_base: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    history: Optional[list[dict]] = None,
    max_tokens: int = 1024,
    timeout: int = 300,
    temperature: float = 0.7,
    reasoning_effort: Optional[str] = None,
) -> Iterator[str]:
    """云端流式调用（SSE），逐段产出增量文本。"""
    import json as _json

    import requests

    if not api_key:
        raise RuntimeError("未配置有效 API Key")
    body = {
        "model": model,
        "messages": _cloud_messages(system, user, history),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    with requests.post(
        f"{api_base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
        stream=True,
    ) as resp:
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f"云端调用失败（HTTP {resp.status_code}）：{resp.text[:300]}")
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                delta = _json.loads(data)["choices"][0]["delta"].get("content") or ""
            except Exception:
                delta = ""
            if delta:
                yield delta


def probe_cloud(api_base: str, api_key: str, timeout: Optional[float] = None) -> dict:
    """轻量探测云端链路：只发一个 GET /models，不消耗生成额度。

    收到任何 HTTP 响应（含 401 未授权）都说明链路可达——这里测的是「网络+服务
    存活」，Key 有效性由真实的 chat 调用去验证。
    """
    import requests

    t0 = time.perf_counter()
    timeout = timeout or _env_float("ROUTE_PROBE_TIMEOUT", 6.0)
    try:
        resp = requests.get(
            f"{api_base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
        )
        reachable = resp.status_code < 500   # 401/403 也算链路通，只是 Key 有问题
        return {
            "reachable": reachable,
            "status_code": resp.status_code,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": "" if reachable else f"服务端错误 HTTP {resp.status_code}",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status_code": 0,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }


# ══════════════════════════════════════════════════════════════
# 六、调用统计（论文指标数据源）
# ══════════════════════════════════════════════════════════════


@dataclass
class _Bucket:
    count: int = 0
    ok: int = 0
    degraded: int = 0
    latencies: list[int] = field(default_factory=list)

    def snapshot(self) -> dict:
        lat = sorted(self.latencies)
        n = len(lat)

        def pct(p: float) -> int:
            if not n:
                return 0
            idx = min(n - 1, max(0, int(round(p / 100 * (n - 1)))))
            return lat[idx]

        return {
            "count": self.count,
            "ok": self.ok,
            "error": self.count - self.ok,
            "degraded": self.degraded,
            "success_rate": round(self.ok / self.count * 100, 1) if self.count else 0.0,
            "avg_latency_ms": round(sum(lat) / n) if n else 0,
            "p50_latency_ms": pct(50),
            "p95_latency_ms": pct(95),
        }


class RouteStats:
    """按 (task, engine) 分桶的滚动统计（默认保留最近 500 条明细）。"""

    def __init__(self, keep: int = 500) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._recent: list[dict] = []
        self._keep = keep

    def record(self, result: RouteResult) -> None:
        with self._lock:
            key = (result.task, result.engine or "none")
            b = self._buckets.setdefault(key, _Bucket())
            b.count += 1
            b.ok += 1 if result.ok else 0
            b.degraded += 1 if result.degraded else 0
            b.latencies.append(result.latency_ms)
            if len(b.latencies) > 1000:
                b.latencies = b.latencies[-1000:]
            entry = result.as_dict()
            entry["at"] = time.time()
            self._recent.append(entry)
            if len(self._recent) > self._keep:
                self._recent = self._recent[-self._keep:]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "by_task_engine": {f"{t}|{e}": b.snapshot() for (t, e), b in sorted(self._buckets.items())},
                "recent": list(self._recent[-20:]),
                "total_calls": sum(b.count for b in self._buckets.values()),
            }

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._recent.clear()


route_stats = RouteStats()


def _push_prometheus(result: RouteResult) -> None:
    """把耗时推给既有 Prometheus 指标（Grafana 可按引擎/任务出图）。"""
    try:
        from .metrics import metrics

        metrics.record_ai(f"{result.engine or 'none'}:{result.task}", result.latency_ms / 1000)
    except Exception:
        pass  # 指标失败绝不影响主流程


# ══════════════════════════════════════════════════════════════
# 七、路由核心
# ══════════════════════════════════════════════════════════════


def _engine_order(task: str, choice: str) -> list[str]:
    """按任务类型 + 策略给出引擎尝试顺序（前面的优先，失败依次后退）。"""
    task = (task or "short").strip().lower()
    if choice == ENGINE_LOCAL:
        return [ENGINE_LOCAL]
    if choice == ENGINE_CLOUD:
        return [ENGINE_CLOUD]
    # auto
    if task in LONG_TASKS:
        order = [ENGINE_CLOUD]
        # 长任务默认不降级到本地：1.5B 模型生成整份剧本质量不可靠，
        # 交给上层 P1「离线样例剧本」兜底更稳。需要时可开 LONG_LOCAL_FALLBACK=1。
        if _env_bool("LONG_LOCAL_FALLBACK", False):
            order.append(ENGINE_LOCAL)
        return order
    # 短任务：本地优先
    return [ENGINE_LOCAL, ENGINE_CLOUD]


def _local_budget(max_tokens: int, task: str) -> int:
    """本地引擎的输出预算。

    短任务在 CPU 上跑 1.5B 模型若不限流，可能连续生成数十秒（判题本该秒回）。
    长任务（本地生成剧本）则不设限，尊重调用方给出的预算。
    """
    if (task or "short").strip().lower() in LONG_TASKS:
        return max_tokens
    return min(max_tokens, _env_int("LOCAL_MAX_TOKENS", 768))


def _can_use(engine: str, api_key: str) -> tuple[bool, str]:
    """引擎当前是否具备调用条件（不含网络探测，只做本地可用性/Key/熔断判断）。"""
    if engine == ENGINE_LOCAL:
        if not local_available():
            return False, _local_engine.load_error() or "本地模型不可用"
        return True, ""
    if not api_key:
        return False, "未配置有效 API Key"
    if not _cloud_health.allow():
        return False, f"云端已熔断（{_cloud_health.state}），暂走本地"
    return True, ""


def route_chat(
    api_base: str = "",
    api_key: str = "",
    model: str = "",
    system: str = "",
    user: str = "",
    history: Optional[list[dict]] = None,
    task: str = "short",
    max_tokens: int = 512,
    timeout: int = 100,
    temperature: Optional[float] = None,
    engine: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> RouteResult:
    """按任务路由一次非流式对话，返回 RouteResult（含引擎/耗时/是否降级）。

    task：short|grade|eval|lecture|chat（本地优先） / long|generate（云端优先）。
    引擎不可用时自动后退到下一个候选；全部失败抛 RouteError。
    """
    choice = engine_choice(engine)
    order = _engine_order(task, choice)
    temp_short = _env_float("LOCAL_TEMPERATURE", 0.2) if temperature is None else temperature
    tried: list[str] = []

    for idx, eng in enumerate(order):
        can, reason = _can_use(eng, api_key)
        if not can:
            tried.append(f"{eng}(跳过: {reason})")
            continue
        task_temp = temperature if temperature is not None else (temp_short if eng == ENGINE_LOCAL else 0.4)
        budget = _local_budget(max_tokens, task)
        t0 = time.perf_counter()
        try:
            if eng == ENGINE_LOCAL:
                text = _local_engine.chat(
                    system=system, user=user, history=history,
                    max_tokens=budget, temperature=task_temp,
                )
                used_model = Path(model_path()).name
            else:
                text = cloud_chat(
                    api_base, api_key, model, system=system, user=user, history=history,
                    max_tokens=max_tokens, timeout=timeout, temperature=task_temp,
                    reasoning_effort=reasoning_effort,
                )

                used_model = model
                _cloud_health.record_success()
            res = RouteResult(
                text=text, engine=eng, task=task, model=used_model,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                ok=True, degraded=idx > 0, fallback_from=order[0] if idx > 0 else "",
            )
            if res.degraded:
                logger.info("路由降级：%s → %s（task=%s）", order[0], eng, task)
            route_stats.record(res)
            _push_prometheus(res)
            return res
        except Exception as exc:
            if eng == ENGINE_CLOUD:
                _cloud_health.record_failure(str(exc))
            else:
                logger.warning("本地引擎调用失败：%s", exc)
            tried.append(f"{eng}(失败: {str(exc)[:120]})")

    res = RouteResult(task=task, ok=False, error="; ".join(tried) or "无可用引擎")
    route_stats.record(res)
    raise RouteError(res.error)


def route_stream(
    api_base: str = "",
    api_key: str = "",
    model: str = "",
    system: str = "",
    user: str = "",
    history: Optional[list[dict]] = None,
    task: str = "chat",
    max_tokens: int = 1024,
    timeout: int = 300,
    temperature: Optional[float] = None,
    engine: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    ctx: Optional[RouteCtx] = None,
) -> Iterator[str]:
    """流式路由：逐段产出增量文本，结束后把路由画像写入 ctx.result。

    降级边界：只有在「尚未吐出任何内容」时才允许切换引擎；
    已经吐了一半再失败则就地结束（不能让用户看到两段拼起来的回答）。
    """
    choice = engine_choice(engine)
    order = _engine_order(task, choice)
    tried: list[str] = []

    for idx, eng in enumerate(order):
        can, reason = _can_use(eng, api_key)
        if not can:
            tried.append(f"{eng}(跳过: {reason})")
            continue
        task_temp = temperature if temperature is not None else (0.7 if eng == ENGINE_CLOUD else 0.5)
        budget = _local_budget(max_tokens, task)
        t0 = time.perf_counter()
        first_token_ms = 0
        emitted = False
        try:
            gen = (
                _local_engine.stream(system=system, user=user, history=history,
                                     max_tokens=budget, temperature=task_temp)
                if eng == ENGINE_LOCAL
                else cloud_stream(api_base, api_key, model, system=system, user=user,
                                  history=history, max_tokens=max_tokens, timeout=timeout,
                                  temperature=task_temp,
                                  reasoning_effort=reasoning_effort)
            )
            for delta in gen:
                if not first_token_ms:
                    first_token_ms = int((time.perf_counter() - t0) * 1000)
                emitted = True
                yield delta
            if eng == ENGINE_CLOUD:
                _cloud_health.record_success()
            res = RouteResult(
                engine=eng, task=task, model=(model if eng == ENGINE_CLOUD else Path(model_path()).name),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                first_token_ms=first_token_ms, ok=True,
                degraded=idx > 0, fallback_from=order[0] if idx > 0 else "",
            )
            route_stats.record(res)
            _push_prometheus(res)
            if ctx is not None:
                ctx.result = res
            return
        except Exception as exc:
            if eng == ENGINE_CLOUD:
                _cloud_health.record_failure(str(exc))
            else:
                logger.warning("本地引擎流式失败：%s", exc)
            tried.append(f"{eng}(失败: {str(exc)[:120]})")
            if emitted:
                # 流已开始：无法回退，记一次失败即可（前端已收到部分内容）
                res = RouteResult(engine=eng, task=task, ok=False,
                                  latency_ms=int((time.perf_counter() - t0) * 1000),
                                  error=f"流式中途中断：{str(exc)[:200]}")
                route_stats.record(res)
                if ctx is not None:
                    ctx.result = res
                return

    res = RouteResult(task=task, ok=False, error="; ".join(tried) or "无可用引擎")
    route_stats.record(res)
    if ctx is not None:
        ctx.result = res
    raise RouteError(res.error)


def route(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    task: str = "short",
    max_tokens: int = 512,
    timeout: int = 100,
    system: str = "",
    reasoning_effort: Optional[str] = None,
) -> tuple[str, str]:
    """兼容旧签名：返回 (text, engine)。新代码请用 route_chat 拿完整画像。"""
    res = route_chat(
        api_base=api_base, api_key=api_key, model=model,
        system=system, user=prompt, task=task,
        max_tokens=max_tokens, timeout=timeout,
        reasoning_effort=reasoning_effort,
    )
    return res.text, res.engine


def route_stream_long_text(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 48000,
    timeout: int = 600,
    system: str = "",
    reasoning_effort: Optional[str] = None,
) -> tuple[str, str]:
    """兼容旧签名：长任务（生成剧本）文本返回，返回 (text, engine)。

    云端失败时不静默吞错——抛 RouteError，交给上层 P1 离线样例剧本兜底。
    """
    res = route_chat(
        api_base=api_base, api_key=api_key, model=model,
        system=system, user=prompt, task="long",
        max_tokens=max_tokens, timeout=timeout,
        reasoning_effort=reasoning_effort,
    )
    return res.text, res.engine


# ══════════════════════════════════════════════════════════════
# 八、看门狗：后台周期探测云端，恢复后自动回切
# ══════════════════════════════════════════════════════════════

_watchdog_started = False
_watchdog_lock = threading.Lock()


def _watchdog_loop(api_base_getter, api_key_getter, interval: float) -> None:
    """守护线程：持续监听云端，链路恢复即回切 cloud（论文「网络自适应」的落点）。"""
    while True:
        try:
            time.sleep(interval)
            state = _cloud_health.state
            if state == "closed":
                continue          # 本来就正常，不必探测（省流量）
            if not _cloud_health.allow():
                continue          # 冷却期未过
            info = probe_cloud(api_base_getter(), api_key_getter())
            if info["reachable"]:
                _cloud_health.record_success()
                logger.info("看门狗探测到云端恢复（%dms），已回切 cloud", info["latency_ms"])
            else:
                logger.debug("看门狗探测：云端仍未恢复 %s", info["error"])
        except Exception as exc:
            logger.debug("看门狗异常：%s", exc)


def start_watchdog(api_base_getter, api_key_getter) -> bool:
    """启动云端健康看门狗（幂等）。需要从数据库读设置的场景用 getter 延迟取值。"""
    global _watchdog_started
    if not _env_bool("ROUTE_WATCHDOG", True):
        return False
    with _watchdog_lock:
        if _watchdog_started:
            return False
        interval = max(10.0, _env_float("ROUTE_WATCHDOG_INTERVAL", 60.0))
        threading.Thread(
            target=_watchdog_loop,
            args=(api_base_getter, api_key_getter, interval),
            name="llm-cloud-watchdog",
            daemon=True,
        ).start()
        _watchdog_started = True
        logger.info("云端健康看门狗已启动（每 %.0fs 探测一次）", interval)
        return True


# ══════════════════════════════════════════════════════════════
# 九、状态快照（供 /api/llm/status 与前端设置面板展示）
# ══════════════════════════════════════════════════════════════


def status(api_base: str = "", api_key: str = "", model: str = "") -> dict:
    """路由层完整状态：策略、两引擎可用性、熔断态、调用统计。"""
    _ensure_env_loaded()
    choice = engine_choice()
    local = _local_engine.snapshot()
    cloud_state = _cloud_health.snapshot()
    probe = probe_cloud(api_base, api_key) if api_base else {
        "reachable": False, "status_code": 0, "latency_ms": 0, "error": "未配置 API 地址",
    }
    return {
        "engine_choice": choice,
        "policy": {
            "short_tasks": sorted(SHORT_TASKS),
            "long_tasks": sorted(LONG_TASKS),
            "short_order": _engine_order("short", choice),
            "long_order": _engine_order("long", choice),
            "long_local_fallback": _env_bool("LONG_LOCAL_FALLBACK", False),
        },
        "local": local,
        "cloud": {
            "engine": ENGINE_CLOUD,
            "configured": bool(api_key),
            "api_base": api_base,
            "model": model,
            "probe": probe,
            **cloud_state,
        },
        "stats": route_stats.snapshot(),
        "effective": {
            "short": _effective_engine("short", choice, api_key),
            "long": _effective_engine("long", choice, api_key),
        },
    }


def _effective_engine(task: str, choice: str, api_key: str) -> str:
    """当前这个任务实际会落到哪个引擎（用于前端展示「判题走本地/生成走云端」）。"""
    for eng in _engine_order(task, choice):
        can, _ = _can_use(eng, api_key)
        if can:
            return eng
    return "none"


def resolve_engine(task: str = "short", api_key: str = "", engine: Optional[str] = None) -> str:
    """预测某任务当前会落到哪个引擎（不发起调用），供日志/前端标注使用。"""
    return _effective_engine(task, engine_choice(engine), api_key)
