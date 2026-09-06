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
    chunk_count: int = 0               # 已入库的本地知识库切块数（0=未建库）


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
    quality_score: Optional[int] = None       # 生成质量自评分（0-100）
    quality_comment: str = ""                 # 生成质量评语/待修问题


class ScriptDetailOut(BaseModel):
    goal_score: Optional[int] = None
    goal_comment: str = ""
    quality_score: Optional[int] = None
    quality_comment: str = ""
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
    web_search: Optional[bool] = None          # None=不变；true/false 才更新
    demo_mode: Optional[bool] = None           # None=不变；true/false 才更新
    review_mode: Optional[str] = None          # smart/naive；None=不变
    llm_engine: Optional[str] = None           # auto/local/cloud 模型路由策略；None=不变
    thinking_level: Optional[str] = None       # high/medium/low 思考强度；None=不变


class SettingsOut(BaseModel):
    api_base: str
    model: str
    web_search: bool
    demo_mode: bool
    review_mode: str = "smart"
    llm_engine: str = "auto"           # 模型路由策略（云端-边缘混合）
    thinking_level: str = "high"       # 思考强度（high/medium/low）
    api_key_set: bool                  # 前端只想知道 Key 是否已配置，不拿 Key 本体
    key_masked: str
    updated_at: str


# ---------- 模型路由（云端-边缘混合降级） ----------

class LlmEngineIn(BaseModel):
    """切换模型路由策略。"""
    engine: str = Field(default="auto", max_length=16)   # auto | local | cloud


class LlmTestIn(BaseModel):
    """单次路由连通性测试（用指定引擎跑一句话）。"""
    engine: str = "auto"                                  # auto | local | cloud
    task: str = "short"                                   # short | long
    prompt: str = Field(default="请用一句话说明什么是进程。", max_length=2000)


class LlmTestOut(BaseModel):
    success: bool
    engine: str = ""                  # 实际生效的引擎
    task: str = "short"
    model: str = ""
    text: str = ""
    latency_ms: int = 0
    degraded: bool = False            # 是否从首选引擎降级
    error: str = ""


class LlmBenchIn(BaseModel):
    """判题基准测试：本地云端同题对比，产出论文可用指标。"""
    engines: str = "local,cloud"      # 要对比的引擎，逗号分隔（不可用的会自动跳过）
    limit: int = 0                    # 只跑前 N 条（0=全部）


class LlmBenchOut(BaseModel):
    """基准测试结果：按引擎给出准确率与延迟分位，并给出两者一致率。"""
    total_cases: int
    engines: dict                     # {engine: {accuracy, correct, total, avg_latency_ms, p50, p95, latency_list}}
    agreement: Optional[float] = None # 本地与云端判定一致率（%）
    cases: list                       # 逐题明细：两引擎各自判定与标准答案
    note: str = ""


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
    quote: str = Field(default="", max_length=2000)   # 输入边界：防超大负载
    picked_index: Optional[int] = None    # 选择题用户选择下标
    attempts: Optional[int] = 1          # 第几次作答（错题本/学习报告用）
    time_cost: Optional[int] = 0         # 本次作答耗时（毫秒，学习报告用）
    retested: bool = False               # 复习模式答对：把该错题标记为「已复练」（保留历史）


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
    question: str = Field(..., max_length=2000)   # 输入边界
    context: str = Field(default="", max_length=2000)


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
    """错题条目：从 analytics 中 is_correct=False 的记录提炼。

    retested: 是否已被「只看错题/错题本」复习答对（保留历史，可筛选待复练）。
    wrong_count: 该题累计答错次数（供分级/排序）。
    review_count: 成功复练次数（遗忘曲线阶段）。
    next_due: 下次应复习日期（ISO yyyy-mm-dd）。
    due_now: 是否今日待复习（遗忘曲线）。
    """
    chapter_index: int
    step_index: int
    question_text: str
    your_answer: str
    correct_answer: str
    explain: str
    retested: bool = False
    wrong_count: int = 1
    review_count: int = 0
    next_due: str = ""
    due_now: bool = False


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


# ---------- 学情诊断 / 自适应推荐（智能学情分析） ----------

class DiagnosisPointOut(BaseModel):
    """单个知识点的掌握度与推荐动作。"""
    chapter_index: int
    title: str
    mastery: float              # 0-1 掌握度
    covered: bool               # 是否已作答过
    status: str                 # weak / due / ok / untouched
    review_count: int           # 已复练次数（遗忘曲线）
    next_due: str               # 下次应复习日期
    prerequisite_of: str        # 该点的前置知识点标题（上一章；首章为空）
    needs_prereq: bool          # 是否需要先补前置（根因优先）
    recommended_action: str


class DiagnosisOut(BaseModel):
    """学情诊断：掌握度 + 前置依赖 + 自适应复习推荐 + 学习时长。"""
    script_id: int
    script_title: str
    review_mode: str            # smart / naive
    total_study_minutes: float  # 累计学习时长（分钟）
    active_days: int            # 活跃作答天数
    next_review_priority: List[int]   # 建议复习的知识点顺序（chapter_index）
    points: List[DiagnosisPointOut]


# ---------- 学习报告（analytics 聚合） ----------

class AnalyticsOverviewOut(BaseModel):
    script_id: int
    script_title: str
    radar: List[dict]              # [{name: 章节标题, value: 章节得分(平均正确率%)}]
    chapters_accuracy: List[dict]  # [{chapter_index, title, correct, total, rate}]
    total_questions: int
    total_correct: int
    overall_rate: float
    # —— 四维新增（C2 报告扩展）——
    time_series: List[dict] = []            # [{date, total, correct, rate}] 按天作答量/正确率
    type_distribution: List[dict] = []      # [{quiz_type, correct, total, rate}] 按题型
    coverage: dict = {}                     # {total_chapters, covered_chapter_indices:[...], covered_count}
    # —— 行为埋点（⑤）——
    total_study_minutes: float = 0          # 累计学习时长（分钟，Σ time_cost）
    active_days: int = 0                    # 活跃作答天数