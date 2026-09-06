#!/usr/bin/env python
# ═══════════════════════════════════════════════════════════════
#  本地模型（Qwen2.5-1.5B-Instruct Q4）一键安装脚本
#  作用：把「云端-边缘混合路由层」需要的本地推理能力装到当前 Python 环境。
#
#  装两样东西：
#    1) llama-cpp-python（GGUF 本地推理，进程内、零外部请求、可离线）
#    2) Qwen2.5-1.5B-Instruct Q4_K_M.gguf 模型权重（默认放 ../models/）
#
#  用法（在项目 backend/ 目录下）：
#    python install_local_llm.py            # 装推理库 + 下载模型
#    python install_local_llm.py --no-model # 只装推理库（模型已有时）
#    python install_local_llm.py --model-only  # 只下载模型
#
#  说明：Windows + Python 3.13 上没有现成轮子需要本地编译，本脚本直接拉
#  abetlen 发布的预编译 wheel（含 AVX2 等指令集加速），免编译、秒装。
#  其它平台/版本会回退到 `pip install llama-cpp-python`（可能需本机编译工具链）。
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")

MODEL_URL = "https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

# abetlen/llama-cpp-python 发布的预编译 wheel 版本（含 Windows 现成轮子）
LLAMA_CPP_VERSION = "0.3.35"
WHEEL_BASE = f"https://github.com/abetlen/llama-cpp-python/releases/download/v{LLAMA_CPP_VERSION}/llama_cpp_python-{LLAMA_CPP_VERSION}"


def _py_tag() -> str:
    """返回如 cp313 / cp311 的 wheel 标签。"""
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def install_library() -> bool:
    """安装 llama-cpp-python。优先用预编译 wheel，失败回退 pip 源编译。"""
    tag = _py_tag()
    is_win = platform.system() == "Windows"
    # 仅 Windows + CPython 提供 py3-none-win_amd64 通用轮子（不绑定具体 cp 版本）
    wheel = None
    if is_win:
        wheel = f"{WHEEL_BASE}-py3-none-win_amd64.whl"
    # 其它平台尝试 cp 标签轮子；拿不到就交 pip 解决（可能编译）
    else:
        wheel = f"{WHEEL_BASE}-{tag}-none-{platform.machine().lower()}.whl"

    print(f"[1/2] 安装 llama-cpp-python（Python {tag}，{'Windows' if is_win else platform.system()}）…")
    try:
        if wheel:
            print(f"     尝试预编译 wheel：{wheel}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", wheel])
            return True
    except subprocess.CalledProcessError:
        print("     预编译 wheel 不可用，回退到 pip 源（可能需要本机编译工具链）…")
    # 回退
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "llama-cpp-python"])
    return True


def download_model() -> bool:
    os.makedirs(MODELS_DIR, exist_ok=True)
    dest = os.path.join(MODELS_DIR, MODEL_NAME)
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"[2/2] 模型已存在，跳过下载：{dest}")
        return True
    print(f"[2/2] 下载模型（约 1 GB，使用 hf-mirror 镜像加速）：{MODEL_URL}")
    try:
        # 断点续传 + 进度
        def _progress(block_num, block_size, total_size):
            if total_size > 0:
                pct = min(100, block_num * block_size * 100 // total_size)
                sys.stdout.write(f"\r     进度 {pct}%  ({block_num * block_size // 1024 // 1024} MB)")
                sys.stdout.flush()

        urllib.request.urlretrieve(MODEL_URL, dest, _progress)
        print(f"\n     完成：{dest}  ({os.path.getsize(dest) // 1024 // 1024} MB)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"\n     下载失败：{exc}")
        print("     可手动从 https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF 下载并放到 models/ 目录。")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="安装本地模型推理能力（Qwen2.5-1.5B + llama-cpp-python）")
    ap.add_argument("--no-model", action="store_true", help="只装推理库，不下载模型")
    ap.add_argument("--model-only", action="store_true", help="只下载模型")
    args = ap.parse_args()

    ok = True
    if not args.model_only:
        ok = install_library()
    if not args.no_model and ok:
        ok = download_model() and ok

    if ok:
        print("\n✅ 安装完成。启动后端后：设置 → 模型路由 → 选「本地优先」或「自动」即可离线判题/讲师。")
        print("   探测状态可在「模型路由」面板点「探测两引擎」查看本地模型加载情况。")
        return 0
    print("\n❌ 安装未完成，请根据上面报错信息排查（多为网络或编译工具链问题）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
