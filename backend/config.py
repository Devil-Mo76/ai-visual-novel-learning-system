"""后端配置：从环境变量/.env 读取数据库连接与默认 AI 参数。

优先 PostgreSQL，若 DATABASE_URL 为空或不可用则回退 SQLite（答辩演示更省事）。
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings

# 数据库文件锚定到 backend/ 目录本身，无论从哪个工作目录启动，
# SQLite 都固定在 backend/learning.db，不会被 cwd 左右（曾因相对路径踩坑）。
BACKEND_DIR = Path(__file__).resolve().parent
# 项目根目录（frontend/）：uploads 原始文件与 knowledge 知识库都放这里，随项目走
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    database_url: str = ""          # 留空则用 SQLite
    sqlite_path: str = str(BACKEND_DIR / "learning.db")

    default_api_base: str = "https://api.deepseek.com"   # DeepSeek 官方 API（OpenAI 兼容协议）
    default_model: str = "deepseek-v4-flash"             # DeepSeek V4：flash(均衡)/pro(强)/flash-vision-exp(多模态)
    cors_origins: str = "*"         # 开发期放开，答辩可按需收窄

    # —— 用户认证（JWT）——
    # 通过环境变量 AUTH_SECRET 注入（.env）；未配置时进程启动时随机生成，
    # 重启后旧 token 失效——本地演示可用，正式部署务必显式配置。
    auth_secret: str = ""
    token_expire_minutes: int = 60 * 24 * 7                  # 默认 7 天有效期

    # —— 结构化日志（Loguru）——
    log_dir: str = str(BACKEND_DIR / "logs")                 # 按日期切分的日志目录

    # —— 本地文件：用户上传原始文件 + 本地知识库（均在项目内，可随项目拷走）——
    uploads_dir: str = str(PROJECT_ROOT / "uploads")         # 上传文件落盘根目录
    knowledge_dir: str = str(PROJECT_ROOT / "knowledge")     # 知识库（切块+索引）根目录

    class Config:
        env_file = ".env"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        # 同步 SQLite：配合同步引擎 + 同步 session，答辩演示零配置
        return f"sqlite:///{self.sqlite_path}"


settings = Settings()

# 未显式配置 AUTH_SECRET 时，进程内随机生成（不落盘、不写入代码库）。
if not settings.auth_secret:
    import secrets as _secrets
    settings.auth_secret = _secrets.token_urlsafe(48)