"""ORM 模型：users / documents / scripts / progress / settings / analytics / lecture_history。

- users: 系统用户（后端真实认证：JWT 登录签发 token，数据按 user_id 物理隔离）。
- documents: 用户上传的学习资料（Word/PDF），存解析出的纯文本，按 user_id 归属。
- scripts: AI 生成的教学剧本（含 chapters/steps 的完整 JSON），按 user_id 归属。
- progress: 学习进度。slot=0 为主槽（自动保存），slot=1..9 为手动存档，按 user_id 归属。
- settings: 单行配置表（API 地址 / Key / 模型名）。全局共享、不按用户过滤。
- analytics: 答题分析。每次判题（含本地选择题判题）落库一行答题行为。
- lecture_history: 讲师一对一对话记录（持久化多轮记忆，替换原进程内内存字典）。
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")          # 解析后的纯文本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    scripts: Mapped[list["Script"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(255), default="")    # 学习资料文件名
    chapters: Mapped[list] = mapped_column(JSON, default=list)      # 完整剧本 chapters
    # —— 学习目标匹配度校验（生成后置的轻量 AI 评分）——
    goal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0-100 匹配度得分
    goal_comment: Mapped[str] = mapped_column(Text, default="")              # 评估评语
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now        # 人机协同手动更新时自动刷新
    )

    document: Mapped["Document"] = relationship(back_populates="scripts")


class Progress(Base):
    __tablename__ = "progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 0=主槽, 1-9=手动
    chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)  # 单行
    api_base: Mapped[str] = mapped_column(String(255), default="https://api.siliconflow.cn/v1")
    api_key: Mapped[str] = mapped_column(String(255), default="")          # 只落后端
    model: Mapped[str] = mapped_column(String(100), default="deepseek-ai/DeepSeek-V3")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Analytics(Base):
    """答题分析：每次判题（含本地选择题判题）落库一行作答行为。"""

    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    quiz_type: Mapped[str] = mapped_column(String(16), default="choice")
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)      # 第几次作答
    time_cost: Mapped[int] = mapped_column(Integer, default=0)     # 作答耗时（毫秒）
    # —— 错题本回溯字段（供 /wrong_questions 直接输出，不依赖章节 JSON）——
    question_text: Mapped[str] = mapped_column(Text, default="")
    your_answer: Mapped[str] = mapped_column(Text, default="")
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    explain: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class LectureHistory(Base):
    """讲师一对一对话记录：永久化多轮记忆（user_id + script_id 维度）。"""

    __tablename__ = "lecture_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)