"""Pydantic 请求/响应模型：剧本结构、进度、设置、文档。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------- 剧本节点 ----------

class LineNode(BaseModel):
    type: Literal["line"] = "line"
    speaker: Literal["teacher", "student"]
    text: str
    talk_emo: str = "jiangjie"        # 说话者表情标签
    listen_emo: str = "sikao"         # 倾听者表情标签


class QuestionNode(BaseModel):
    """弹题节点，支持三种题型：
    - 选择题 (quiz_type="choice")：choices+answer(下标)
    - 填空题 (quiz_type="fill")：answer_text 参考答案，AI 判题
    - 简答题 (quiz_type="short")：reference_points 参考答案要点，AI 判题（复述 70%-80% 通过）
    """
    type: Literal["question"] = "question"
    speaker: Literal["teacher", "student"]
    text: str                         # 题目/提问语
    talk_emo: str = "tiwen"
    listen_emo: str = "sikao"
    quiz_type: Literal["choice", "fill", "short"] = "choice"
    # 选择题用
    choices: Optional[List[str]] = None
    answer: Optional[int] = None      # 选择题：正确答案下标
    # 填空/简答用
    answer_text: Optional[str] = None          # 填空参考答案
    reference_points: Optional[list] = None    # 简答参考答案要点（AI 判题依据）
    explain: str = ""                 # 讲评（答完题后展示）


ScriptStep = LineNode | QuestionNode


class ChapterNode(BaseModel):
    id: str
    title: str
    background: str                   # 背景图 key（前端映射，如 "客厅"）
    steps: List[ScriptStep] = Field(..., min_length=1)


class ScriptPayload(BaseModel):
    """完整剧本（数据库持久化的是这份 JSON 的 dict 形式）。"""
    title: str
    source: str = ""
    chapters: List[ChapterNode] = Field(..., min_length=1)


# ---------- API 请求/响应 ----------

class DocumentOut(BaseModel):
    id: int
    filename: str
    title: str
    content_preview: str = ""          # 只回传前 200 字预览，不整篇回传
    created_at: str
    has_script: bool = False           # 是否已生成过剧本（前端据此显示「进入学习」）
    latest_script_id: Optional[int] = None   # 最近一份剧本 ID


class ScriptGenerateIn(BaseModel):
    document_id: int
    title: Optional[str] = None
    chapter_count: int = Field(8, ge=1, le=30)     # 章节数上限放宽到 30：内容多就多分章，保证讲透
    learning_goal: Optional[str] = None            # 用户对文档背景/学习目标的说明，如“考研专业课资料”
    quiz_types: List[Literal["choice", "fill", "short"]] = Field(default_factory=lambda: ["choice"])  # 弹题类型集合


class ScriptGenerateOut(BaseModel):
    script_id: int
    script: ScriptPayload
    goal_score: Optional[int] = None          # 学习目标匹配度得分（0-100；评估失败/未填目标时为 None）
    goal_comment: str = ""                    # 学习目标匹配度评语


class ScriptDetailOut(BaseModel):
    goal_score: Optional[int] = None
    goal_comment: str = ""
    script_id: int
    document_id: int
    title: str
    source: str
    chapters: List[ChapterNode]


class ProgressSaveIn(BaseModel):
    script_id: int
    slot: int = Field(0, ge=0, le=9)
    chapter_index: int = Field(0, ge=0)
    step_index: int = Field(0, ge=0)


class ProgressOut(BaseModel):
    script_id: int
    slot: int
    chapter_index: int
    step_index: int
    updated_at: str


class SettingsIn(BaseModel):
    # 均可选：缺失时后端回退到数据库里已保存的值（用于连接测试免填）
    api_base: str = ""
    api_key: str = ""
    model: str = ""


class SettingsOut(BaseModel):
    api_base: str
    model: str
    api_key_set: bool                  # 前端只想知道 Key 是否已配置，不拿 Key 本体
    key_masked: str
    updated_at: str


class TestResult(BaseModel):
    success: bool
    message: str


class AnswerIn(BaseModel):
    """判题请求：填空题/简答题答案由 AI 判断。
    quote 字段：填空题传填写的词句；简答题传用户复述内容。
    """
    script_id: int
    chapter_index: int
    step_index: int
    quiz_type: Literal["choice", "fill", "short"]
    quote: str = ""
    picked_index: Optional[int] = None    # 选择题用户选择下标
    attempts: Optional[int] = 1          # 第几次作答（错题本/学习报告用）
    time_cost: Optional[int] = 0         # 本次作答耗时（毫秒，学习报告用）


class AnswerOut(BaseModel):
    correct: bool
    explain: str
    message: str = ""


class ArchiveOut(BaseModel):
    """存档条目：标注用户导入的资料（文档）名称。"""
    script_id: int
    slot: int                # 0=自动档，1-9=手动档
    chapter_index: int
    step_index: int
    updated_at: str
    document_title: str      # 用户导入的资料名（文档标题）


# ---------- 讲师一对一辅导 ----------

class LectureChatIn(BaseModel):
    """讲师模式提问请求。

    - script_id：当前学习的剧本（据此取关联的学习资料 + 会话记忆）。
    - question：用户针对疑难知识点提出的问题。
    - context：可选，当前所处上下文（章节标题 / 弹题题目 / 讲评），
      由前端拼好后传入，帮助讲师知道用户在哪儿卡住。
    """
    script_id: int
    question: str
    context: str = ""


class LectureEndIn(BaseModel):
    """退出讲师模式：清空该剧本的讲师会话记忆。"""
    script_id: int


# ---------- 用户认证 ----------

class RegisterIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, description="用户名，唯一")
    password: str = Field(..., min_length=6, max_length=128, description="密码，至少 6 位")


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    created_at: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 错题本 ----------

class WrongQuestionOut(BaseModel):
    """错题条目：从 analytics 中 is_correct=False 的记录提炼。"""
    chapter_index: int
    step_index: int
    question_text: str
    your_answer: str
    correct_answer: str
    explain: str


# ---------- 剧本手动更新（人机协同） ----------

class ScriptUpdateIn(BaseModel):
    """前端编辑后的完整剧本章节数组（仅做章节字段的格式校验，不重新调 AI）。"""
    chapters: List[ChapterNode] = Field(..., min_length=1)


# ---------- 讲师历史查询 ----------

class LectureHistoryRecordOut(BaseModel):
    id: int
    role: str                      # user / assistant
    content: str
    created_at: str


# ---------- 学习报告（analytics 聚合） ----------

class AnalyticsOverviewOut(BaseModel):
    script_id: int
    script_title: str
    radar: List[dict]              # [{name: 章节标题, value: 章节得分(平均正确率%)}]
    chapters_accuracy: List[dict]  # [{chapter_index, title, correct, total, rate}]
    total_questions: int
    total_correct: int
    overall_rate: float