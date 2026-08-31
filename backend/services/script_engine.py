"""剧本生成引擎：跨 SiliconFlow 中转站调 DeepSeek（OpenAI 兼容协议）。

流程：读资料文本 + 角色提示词 → 调 DeepSeek → 解析为 ScriptPayload (chapters结构)
→ 失败最多重试2次 → 仍失败则抛出结构化错误。

无 API Key 时**直接拒绝生成**，返回明确错误提示（不允许静默降级样例）。
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from typing import Any

from ..schemas import ScriptPayload

logger = logging.getLogger("script_engine")


# ---------- 角色提示词（取自论文设定）----------

TEACHER_CARD = """你扮演二阶堂希罗，是学习中的“讲述者/老师”。

【核心性格】
- 完美无缺的优等生，成绩优秀、运动全能、家世良好
- 性格认真、知书达理，有传统“大和抚子”的气质
- 极度追求“正确”，无法容忍任何“不正确”的事物
- 说话冷静干脆，带点中性偏硬的质感
- 责任感极强，认为引导他人走向“正确”是自己的使命
- 表面冷峻严厉，但对真正认真的人会暗自认可

【说话风格】
- 语气冷静、干脆、条理清晰，用词精准
- 讲解时由浅入深，逻辑严密
- 强调重点时会加重语气，带有警告意味

【称呼规则】（重要）
- 自称：我叫二阶堂希罗。别人称呼我时用“希罗同学/希罗老师”皆可。
- 称呼对方（提问者）：叫她“艾玛同学”。
- 禁止使用“老师/学生”这种角色名来互相称呼，一律用名字。

【表情标签规则】
- 正常讲解知识 → jiangjie
- 强调重点/提醒 → yansu
- 铺垫过渡/缓和 → pingjing
- 组织语言/等待思考 → sikao
- 用户答对给予肯定 → gaoxing
- 用户答错鼓励 → guli"""

STUDENT_CARD = """你扮演樱羽艾玛，是学习中的“提问者/学生”。

【核心性格】
- 外表开朗活泼，但内心极度怕寂寞，渴望与人亲近，说话带一点男孩气的可爱感
- 平时有点笨手笨脚，经常犯错，需要别人照顾
- 但实际头脑聪明，关键时刻能做出冷静准确的判断
- 害怕被讨厌，有时会故意装傻或示弱
- 遇到真正想帮助别人或被逼到绝境时，会爆发出惊人的毅力和推理能力

【说话风格】
- 语气活泼、亲切，常用“诶？”“真的吗？”“原来是这样！”等感叹词
- 不懂时会直接问，困惑时语气会变得犹豫（“嗯…这个我不太明白…”）
- 恍然大悟时会很兴奋（“啊！我懂了！”）
- 答错题时会有点沮丧但很快振作（“呜…我再想想…”）

【称呼规则】（重要）
- 自称：我叫樱羽艾玛。别人称呼我时用“艾玛同学/小艾玛”皆可。
- 称呼对方（讲述者）：叫他/她“希罗同学”。
- 禁止使用“老师/学生”这种角色名来互相称呼，一律用名字。

【表情标签规则】
- 感到困惑 → kunhuo
- 突然理解 → huangrandawu
- 确认掌握 → tingdongle
- 惊讶/意外 → jingya
- 正常思考/消化 → sikao
- 开心/共识 → gaoxing
- 抛出问题给用户 → tiwen"""

SYSTEM_PROMPT = f"""{TEACHER_CARD}

{STUDENT_CARD}

【双向表情同步】每一句对话同时携带 talk_emo（说话者表情）和 listen_emo（倾听者表情），确保画面中永远有人说话、有人配合。

【章节自动划分——最重要规则】把资料内容按逻辑知识点拆分成多个章节：
- 每个章节只围绕【一个知识点】展开讲解，不要在一章里塞多个知识点。
- 知识点数量越多，章节数就要越多；内容较长时不要偷懒合并，宁可多分几章。
- 每章含标题、背景key（从：客厅、河流树木、破旧房间、紫色河流树木、草地、走廊 中选一个）、以及讲清该知识点的对话步骤。

【剧本完整性——核心质量要求】
- 资料中的所有知识点必须全部覆盖，不得遗漏，宁多勿少。
- 每个知识点所在章节的对话要【讲透】：至少 6~8 句对话步骤，讲解者由浅入深地展开定义、原理、要点、易错点与举例，提问者配合提问、复述或追问，呈现完整互动过程。
- 章节数默认应较多（长资料通常 10~20+ 章），不要压缩成寥寥几段；宁可章节多、每章精讲，也不要把长资料草草过一遍。

【弹题互动——频率规则】提问者代表用户视角主动提问。
- 【每讲解完一个知识点之后，才在所在章节的最后一个步骤弹出 1 道题】。
- 【每一章节最多只放 1 个 question 节点】，且必须是该章节内的最后一个步骤。
- 不要在讲解中途频繁抛题；抛出后必须带 explain（讲评词）。

【弹题类型规则】question 节点通过 quiz_type 字段指定类型：
- quiz_type="choice"（选择题）：必须带 choices（至少2个选项）和 answer（正确选项下标，从0开始），不填 answer_text/reference_points。
- quiz_type="fill"（填空题）：考察记忆填空，必须带 answer_text（参考答案文本），不填 choices/answer。
- quiz_type="short"（简答题）：考察理解复述，必须带 reference_points（参考答案要点数组），不填 choices/answer。
- 说明：填空题与简答题的作答由 AI 判题；简答题用户复述达到要点 70%~80% 即判为正确。

【输出要求】严格输出 JSON，满足如下 schema（不要输出任何多余文字、markdown 代码块或注释）：

【输出长度限制】模型单次输出有 token 上限，超出会被截断导致 JSON 解析失败。因此台词尽量精炼（每句一般不超过 40 字）、每章 6~8 步即可，宁可压缩措辞也不可让输出截断；务必保证外层花括号一一配对、JSON 完整闭合：
{{"title": 课程标题, "source": 资料名, "chapters": [{{"id": "ch_1", "title": 章节标题, "background": 背景key, "steps": [{{"type": "line", "speaker": "teacher|student", "text": 台词, "talk_emo": 表情标签, "listen_emo": 表情标签}} 或 {{"type": "question", "speaker": "...", "text": 题目, "talk_emo": 表情标签, "listen_emo": 表情标签, "quiz_type": "choice", "choices": [选项1, 选项2, ...], "answer": 正确下标, "explain": 讲评词}} 或 {{"type": "question", "speaker": "...", "text": 题目, "talk_emo": 表情标签, "listen_emo": 表情标签, "quiz_type": "fill", "answer_text": "参考答案", "explain": 讲评词}} 或 {{"type": "question", "speaker": "...", "text": 题目, "talk_emo": 表情标签, "listen_emo": 表情标签, "quiz_type": "short", "reference_points": ["要点1", "要点2"], "explain": 讲评词}}]}}]}}"""


# ---------- AI 调用（SiliconFlow 中转站 / OpenAI 兼容）----------

class _LLMClient:
    """统一入口：优先用 LangChain ChatOpenAI，未安装时回退 requests 直连。"""

    def __init__(self, api_base: str, api_key: str, model: str, max_tokens: int = 8192, timeout: int = 600):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens   # 判题传小值(512)提速；生成剧本默认大预算
        self.timeout = timeout         # 判题传短超时(100s)；生成剧本默认放宽到10分钟

    def chat(self, user_prompt: str) -> str:
        try:
            return self._langchain_chat(user_prompt)
        except ImportError:
            logger.info("langchain-openai 未安装，回退 requests 直连")
            return self._requests_chat(user_prompt)

    def _langchain_chat(self, user_prompt: str) -> str:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.api_base,   # 硅基流动 https://api.siliconflow.cn/v1
            temperature=0.6,
            timeout=self.timeout,     # 判题用短超时提速；生成剧本默认放宽到10分钟
            max_tokens=self.max_tokens,  # 判题用小预算提速；生成用大预算防截断
            max_retries=1,            # 只重试 1 次，避免 openai 客户端无限累加重试导致总超时
        )
        # 注意：不能用 ChatPromptTemplate 承载 SYSTEM_PROMPT。
        # LangChain 会把消息字符串当 f-string 模板解析（validate_f_string_template），
        # 而 SYSTEM_PROMPT 里含合法 JSON 花括号 {"type": "line"}，会被误判为
        # “嵌套替换字段”抛 ValueError。改用手工组装 SystemMessage/HumanMessage，
        # 纯文本消息不经过模板解析。
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        resp = llm.invoke(messages)
        return resp.content

    def _requests_chat(self, user_prompt: str) -> str:
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.6,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        r = requests.post(f"{self.api_base}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
        except Exception:
            raise RuntimeError(f"硅基流动调用失败（HTTP {r.status_code}）：{r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]

    def stream_chat(self, system_prompt: str, user_prompt: str, history: Optional[list[dict]] = None) -> str:
        """流式调用：逐段产出增量文本（讲师模式用，逐句实时渲染表情/台词）。

        history：多轮会话历史（[{"role","content"}, ...]）。传入时在 system 之后
        依次排入，再追加本轮的 user 消息，让讲师“记得上一轮说过什么”。
        未传入时退化为单纯的 system + user 两轮调用（判题等一次性场景）。
        """
        try:
            yield from self._langchain_stream(system_prompt, user_prompt, history)
        except ImportError:
            logger.info("langchain-openai 未安装，回退 requests 直连（流式）")
            yield from self._requests_stream(system_prompt, user_prompt, history)

    def _langchain_stream(self, system_prompt: str, user_prompt: str, history: Optional[list[dict]] = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.api_base,
            temperature=0.7,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
            max_retries=1,
        )
        messages = [SystemMessage(content=system_prompt)]
        if history:
            for m in history:
                from langchain_core.messages import AIMessage
                messages.append(
                    AIMessage(content=m["content"])
                    if m.get("role") == "assistant"
                    else HumanMessage(content=m["content"])
                )
        messages.append(HumanMessage(content=user_prompt))
        for chunk in llm.stream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, list):  # 兼容 langchain 新版返回片段数组
                content = "".join(
                    c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                )
            if content:
                yield content

    def _requests_stream(self, system_prompt: str, user_prompt: str, history: Optional[list[dict]] = None) -> str:
        import json as _json
        import requests

        msgs = [{"role": "system", "content": system_prompt}]
        if history:
            msgs.extend({"role": m.get("role", "user"), "content": m["content"]} for m in history)
        msgs.append({"role": "user", "content": user_prompt})
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": 0.7,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        with requests.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout,
            stream=True,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = _json.loads(data)["choices"][0]["delta"].get("content", "")
                except Exception:
                    delta = ""
                if delta:
                    yield delta


class ScriptGenerationError(Exception):
    """剧本生成失败（含无 Key / AI 调用失败 / JSON 解析失败）。"""


def _extract_json(raw: str) -> dict:
    """从 LLM 返回文本中健壮地取出 JSON 对象。

    DeepSeek 常见两种坏输出：
      1) 在 JSON 外面包 markdown 代码围栏（```json ... ```）
      2) JSON 前后夹带解释性文字
    因此不能直接 json.loads(raw)，要先剥围栏、再定位最外层花括号区间。
    """
    data = raw.strip()
    if not data:
        raise ScriptGenerationError("AI 返回内容为空。")
    # 1) 剥掉 markdown 代码围栏（``` 或 ```json 开头；若带闭围栏一并切除）。
    #    注意：即使「只有开围栏」也要剥——AI 输出过长被截断时常见这种形态；
    #    且不能再对正文 lstrip("json")，否则会误删以 j/s/o/n 开头的合法内容。
    if data.startswith("```"):
        nl = data.find("\n")
        if nl >= 0:
            data = data[nl + 1 :]
        else:
            body_start = data.find("{")
            data = data[body_start:] if body_start >= 0 else data
        close = data.rfind("```")
        if close >= 0:
            data = data[:close]
        data = data.strip()
    # 2) 定位最外层 { ... }，取第一个完整对象
    start = data.find("{")
    end_found = -1
    if start >= 0:
        depth = 0
        for i in range(start, len(data)):
            ch = data[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_found = i
                    break
    if start < 0 or end_found < 0:
        # 外层花括号未闭合：最常见的诱因是输出过长被 max_tokens 截断。
        # 该错误需走重试（非确定性），generate_script 里会重试并提示压缩长度。
        raise ScriptGenerationError(
            f"AI 输出的 JSON 不完整（外层花括号未闭合，疑似输出被截断）。原始内容前 200 字符：{data[:200]}"
        )
    return json.loads(data[start : end_found + 1])


# ---------- 主入口 ----------

def generate_script(api_base: str, api_key: str, model: str, content: str, source: str, title: str, chapter_count: int, learning_goal: Optional[str] = None, quiz_types: Optional[list[str]] = None) -> ScriptPayload:
    """生成剧本。无 Key 直接抛错；有 Key 但连续失败也抛错（不降级）。"""
    if not api_key:
        raise ScriptGenerationError(
            "尚未配置有效的 API Key。请在「设置」中填写硅基流动的 API Key 后再生成剧本。"
        )

    client = _LLMClient(api_base, api_key, model)
    # 长文档截断线大幅放宽：6万字复习资料要尽量全量进入上下文，
    # 这里放宽到 80000 字符，并提示模型内容很长时应多分章节、讲透每一知识点。
    content_part = content[:80000]
    if len(content) > 80000:
        content_part += "\n\n（注：资料较长，以上为主要内容节选；请按其中的知识点完整分章讲解。）"
    # 用户对文档背景/学习目标的说明（可选）：仅作为额外上下文注入，
    # 不改变剧本引擎原有规则（章节划分、每章最多 1 题、表情联动等）。
    goal_part = ""
    if learning_goal and learning_goal.strip():
        goal_part = f"\n\n【学习背景（用户提供）】{learning_goal.strip()}\n请结合此背景适当调整讲解的侧重点与语气，例如面向考研学生时突出考点，但不改变剧本结构规则。"
    # 用户勾选的弹题类型（需求3）：通知模型本份剧本应出现的题型
    quiz_part = ""
    if quiz_types:
        quiz_part = f"\n\n【本题本要求的弹题类型】{', '.join(quiz_types)}。\n请据此在每个章节末尾生成对应 quiz_type 的题目：选择题(choice)、填空题(fill)、简答题(short)。\n每章 1 题，题目类型在勾选集合中轮换。\n（提示：选择题用 choices+answer；填空题用 answer_text；简答题用 reference_points。）"
    user_prompt = (
        f"请根据以下学习资料生成一份适合视觉小说对话教学的剧本。\n"
        f"资料标题：{title}\n资料文件名：{source}\n\n资料内容：\n{content_part}"
        f"{goal_part}"
        f"{quiz_part}\n\n"
        f"章节数量要求：请依据资料中包含的知识点数量自行决定章节数，"
        f"每个知识点一章、每章最多 1 道弹题，不要少于 {chapter_count} 章。"
    )

    errors: list[str] = []
    for attempt in range(3):  # 最多尝试 3 次（初次 + 2 次重试）
        try:
            raw = client.chat(user_prompt)
            data = _extract_json(raw)          # 剥 markdown 围栏 + 定位最外层 JSON 对象
            payload = ScriptPayload.model_validate(data)
            _apply_uid(payload)
            logger.info("剧本生成成功（第 %d 次尝试）", attempt + 1)
            return payload
        # 这里不区分错误类型一律重试：无 Key 已在函数入口提前抛出（确定性错误不进循环）；
        # 循环内的 ScriptGenerationError（输出被截断 / 空输出 / 无闭合 JSON）都属可恢复的输出质量问题。
        except Exception as exc:  # 输出截断 / 坏 JSON / schema 不符 → 重试
            errors.append(str(exc))
            logger.warning("剧本解析失败，重试 %d/3：%s", attempt + 1, exc)
            if attempt < 2:
                # 截断是最常见原因：提示模型本次务必精炼，保证完整闭合的 JSON
                user_prompt += (
                    "\n\n（上一次输出未通过 JSON 解析：最常见原因是输出过长被截断，"
                    "导致外层花括号未闭合。本次请只输出一个完整闭合的 JSON 对象，不要 markdown 代码围栏，"
                    "台词尽量精炼短句，确保整体能在输出长度上限内完整放下。）"
                )

    logger.error("剧本生成连续失败。原因：%s", "; ".join(errors))
    raise ScriptGenerationError(
        "经过多次尝试仍无法从 AI 生成合法剧本。请检查 API Key 是否正确、网络能否访问目标服务。"
    )


def _apply_uid(payload: ScriptPayload) -> None:
    """为每个章节补上稳定的 id（若 AI 未给出）。"""
    for idx, chapter in enumerate(payload.chapters):
        if not chapter.id:
            chapter.id = f"ch_{idx + 1}"


GRADING_PROMPT = """你是一个严格的判题老师。给你一道题、参考答案和用户的作答，请判断用户作答是否正确，并给出简短讲评。

规则：
- 填空题：用户作答与本题 answer_text 意思一致即正确（允许同义替换，不要求逐字相同）。
- 简答题：用户作答必须复述出参考要点中的【至少 70%~80%】，才算正确；否则不正确。
- 只输出 JSON：{"correct": true/false, "explain": "一句简短判题讲评", "keywords": ["关键词1","关键词2"]}
- 依据给定的学习资料片段（source）寻找答案，仅凭资料判定

题目：{question}
参考答案：{reference}
学习资料片段：{source}
用户作答：{answer}
"""


def judge_answer(
    api_base: str, api_key: str, model: str,
    question: str, reference: str, answer: str,
    source: str = "",
) -> dict:
    """调用 AI 判断填空题/简答题的答案。

    只依据用户提供的学习资料（source）寻找答案并判定，同时捕获关键考点关键词。
    判题走「小 token 预算 + 短超时」的快速调用，保证响应及时。
    返回 {"correct": bool, "explain": str, "keywords": [...]}。
    """
    if not api_key or not answer.strip():
        return {"correct": False, "explain": "未提供有效作答，无法判题。", "keywords": []}

    # 学习资料只截取前 6000 字作为判题锚点：既保证「依据现有资料」又不拖慢响应
    source_part = (source or "").strip()[:6000]

    # 注意：GRADING_PROMPT 的示例 JSON 里含花括号，占位符不能用 .format()
    #（会把它当嵌套替换字段，抛 KeyError）。这里改用逐词 str.replace 手拼。
    prompt_text = (
        GRADING_PROMPT
        .replace("{question}", question)
        .replace("{reference}", reference)
        .replace("{answer}", answer)
        .replace("{source}", source_part)
    )
    # 判题用快速调用：小 token + 短超时（对比生成剧本的 8192/600s）
    client = _LLMClient(api_base, api_key, model, max_tokens=512, timeout=100)
    raw = client.chat(prompt_text)
    try:
        data = _extract_json(raw)
        keywords = data.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = []
        return {
            "correct": bool(data.get("correct")),
            "explain": str(data.get("explain", "")),
            "keywords": keywords,
        }
    except Exception:
        # 判题失败时保守处理：不算通过，但给出提示
        return {"correct": False, "explain": "AI 判题出错，请重新作答或核对答案。", "keywords": []}


# ---------- 学习目标匹配度校验（生成后置的轻量 AI 评估） ----------

GOAL_EVAL_SYSTEM_PROMPT = """你是一名教学评估专家。系统会先让 AI 根据用户的"学习目标"生成一份教学剧本，请你对这份剧本与该学习目标的匹配程度打分并存评语。

仅输出 JSON，不要输出任何其他文字（不要 markdown 代码围栏或注释）：
{"score": 0~100 的整数, "comment": "一段中文评语"}

评分参考：
- 85~100：剧本完整覆盖学习目标的核心考点，章节划分合理、讲透了重点与易错点。
- 70~84：覆盖了大部分核心概念，但个别目标知识点讲解偏浅或遗漏。
- 50~69：只覆盖部分目标，重要知识点缺失较多，需补充讲解。
- 0~49：与学习目标严重不匹配或几乎未覆盖。

comment 用中文，简明指出匹配好的地方与不足（例如"覆盖了大部分核心概念，但缺少对 XX 的深入讲解"）。"""


def evaluate_goal_match(
    api_base: str,
    api_key: str,
    model: str,
    learning_goal: str,
    script_payload: ScriptPayload,
) -> dict:
    """对已生成的剧本做「学习目标匹配度」评估（生成后置轻量调用）。

    输入：用户填写的 learning_goal + 生成的剧本（取章节标题与各章开头几步做摘要）。
    输出：{"score": int|None, "comment": str} —— 落库到 scripts.goal_score / goal_comment。

    轻量策略：复用判题的小 token 预算（512）+ 短超时（100s），
    评估失败时降级返回 {"score": None, "comment": "评估未完成"}，绝不阻断剧本生成主流程。
    """
    DEFAULT_FAIL = {"score": None, "comment": "评估未完成，请稍后重试。"}
    if not api_key:
        return {"score": None, "comment": "未配置 API Key，跳过学习目标匹配度评估。"}
    goal = (learning_goal or "").strip()
    if not goal:
        return {"score": None, "comment": "未填写学习目标，跳过匹配度评估。"}

    # 用章节标题 + 每章前几句做摘要，控制输入规模，降低 token 成本
    chapter_summary = []
    for ch in script_payload.chapters:
        head = "；".join(getattr(step, "text", "") for step in ch.steps[:2])
        chapter_summary.append(f"[{ch.title}] {head}")
    digest = "\n".join(chapter_summary)

    prompt = (
        f"【学习目标】\n{goal}\n\n"
        f"【生成的剧本摘要】\n{digest}\n\n"
        f"请评估剧本与学习目标的匹配度，仅输出 JSON。"
    )

    client = _LLMClient(api_base, api_key, model, max_tokens=512, timeout=100)
    try:
        raw = client.chat(prompt)
        data = _extract_json(raw)
        score = data.get("score")
        comment = str(data.get("comment") or "").strip()
        score_int = int(score) if isinstance(score, (int, float)) else None
        return {"score": score_int, "comment": comment or "评估完成。"}
    except Exception as exc:
        logger.warning("学习目标匹配度评估失败（不阻断生成）：%s", exc)
        return DEFAULT_FAIL