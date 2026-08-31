"""后端配置：从环境变量/.env 读取数据库连接与默认 AI 参数。

优先 PostgreSQL，若 DATABASE_URL 为空或不可用则回退 SQLite（答辩演示更省事）。
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings

# 数据库文件锚定到 backend/ 目录本身，无论从哪个工作目录启动，
# SQLite 都固定在 backend/learning.db，不会被 cwd 左右（曾因相对路径踩坑）。
BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    database_url: str = ""          # 留空则用 SQLite
    sqlite_path: str = str(BACKEND_DIR / "learning.db")

    default_api_base: str = "https://api.siliconflow.cn/v1"   # 硅基流动中转站（OpenAI 兼容）
    default_model: str = "deepseek-ai/DeepSeek-V3"
    cors_origins: str = "*"         # 开发期放开，答辩可按需收窄

    # —— 用户认证（JWT）——
    auth_secret: str = "vn-learning-demo-secret-change-me"   # 生产务必改用强随机值
    token_expire_minutes: int = 60 * 24 * 7                  # 默认 7 天有效期

    # —— 结构化日志（Loguru）——
    log_dir: str = str(BACKEND_DIR / "logs")                 # 按日期切分的日志目录

    class Config:
        env_file = ".env"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        # 同步 SQLite：配合同步引擎 + 同步 session，答辩演示零配置
        return f"sqlite:///{self.sqlite_path}"


settings = Settings()