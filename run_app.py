# ═══════════════════════════════════════════════
# run_app.py — 一键启动程序
#
# 职责：
#  1. 检查后端(:8000)是否已在运行，没有则自动拉起 uvicorn
#  2. 检查前端静态站(:8080)是否已在运行，没有则自动拉起 http.server
#  3. 等待后端健康检查通过后，自动打开浏览器
#  4. 按 Ctrl+C 可一次性关掉后端的两个子进程
#
# 用法：
#  python run_app.py
#  或直接双击 start.bat
# ═══════════════════════════════════════════════

import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 老版本 Python 没有 reconfigure 时忽略

# ── 常量 ──
FRONTEND_DIR = Path(__file__).resolve().parent      # 本项目根目录（frontend/）
BACKEND_PORT = 8000
FRONTEND_PORT = 8080
BACKEND_TIMEOUT = 90        # 等待后端启动的最长秒数

children = []               # 所有由本程序拉起的子进程


def say(msg: str) -> None:
    print(f"[启动器] {msg}")


def port_in_use(port: int) -> bool:
    """检查端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_free_port(prefer: int) -> int:
    """优先用 prefer，被占用则从 8001 起找一个空闲端口。"""
    if not port_in_use(prefer):
        return prefer
    for p in range(8001, 8020):
        if not port_in_use(p):
            return p
    return prefer


def backend_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ── 拉起后端 uvicorn ──
def start_backend(port: int):
    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    return subprocess.Popen(cmd, cwd=str(FRONTEND_DIR))


# ── 拉起前端静态服务 ──
def start_frontend(port: int):
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        cwd=str(FRONTEND_DIR),
    )


def main() -> None:
    print("╔══════════════════════════════════════════════╗")
    print("║  AI视觉小说互动式学习系统 · 一键启动          ║")
    print("╚══════════════════════════════════════════════╝")

    backend_port = BACKEND_PORT
    if backend_healthy(backend_port):
        say(f"检测到后端已在 :{backend_port} 运行，直接复用。")
    else:
        if port_in_use(backend_port):
            backend_port = find_free_port(backend_port)
            say(f"端口 {BACKEND_PORT} 被占用，改用 :{backend_port}")
        say(f"正在启动后端（FastAPI，端口 {backend_port}）…")
        children.append(start_backend(backend_port))

        # 等待后端健康检查通过
        waited = 0
        while not backend_healthy(backend_port):
            if waited >= BACKEND_TIMEOUT:
                say(f"后端在 {BACKEND_TIMEOUT}s 内未就绪，请检查依赖是否安装。")
                say("可先手动执行：cd frontend/backend && pip install -r requirements.txt")
                cleanup(1)
            waited += 1
            time.sleep(1)
        say(f"后端就绪 ✅  http://127.0.0.1:{backend_port}")

    frontend_port = FRONTEND_PORT
    if port_in_use(frontend_port):
        frontend_port = find_free_port(frontend_port)
        say(f"前端端口 {FRONTEND_PORT} 被占用，改用 :{frontend_port}")
    say(f"正在启动前端静态服务（端口 {frontend_port}）…")
    children.append(start_frontend(frontend_port))
    # 稍微等一下，保证静态站起来
    time.sleep(1.5)

    url = f"http://localhost:{frontend_port}"
    say(f"前端地址：{url}")
    say("正在打开浏览器…")
    webbrowser.open(url)

    print()
    print("一切就绪。浏览器已打开。")
    print("提示：按 Ctrl+C 可停止后端与前端服务并退出。")
    print()

    try:
        while True:
            time.sleep(1)
            # 任一子进程意外退出就提示
            for idx, p in enumerate(children):
                if p.poll() is not None:
                    say(f"子进程异常退出（exit={p.returncode}），已自动关闭其他进程。")
                    cleanup(1)
    except KeyboardInterrupt:
        say("收到关闭信号，正在停止服务…")
        cleanup(0)


def cleanup(code: int) -> None:
    """依次关闭所有子进程后退出。"""
    for p in children:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(0.5)
    for p in children:
        try:
            p.kill()
        except Exception:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()