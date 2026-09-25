"""讲师一对一辅导服务（需求：用户召唤讲师深入讲解疑难知识点）。

讲师是用户召唤型角色：进入后切换到「一对一辅导」模式，讲师基于已导入的
学习资料 + 通用知识 + （可选）联网搜索信息实时作答，SSE 流式逐段返回，每段
带 talk_emo 表情标签，前端据此实时切换讲师立绘并打字机显示。

会话记忆：同一剧本、同一用户的多轮问答需要连贯（跨章节 / 跨会话）。
升级为读写 lecture_history 表持久化多轮上下文（原本是进程内内存 dict，
重启即丢；现落库，讲师“记住整段学习里聊过什么”），读取最近 N 轮注入。

联网搜索：讲师可选开启，把 DuckDuckGo Instant Answer 的摘要片段附加到上下文；
无结果 / 搜索不可用时自动退化（仅资料 + 通用知识），不阻断回答。

关键设计：**表情标签由模型每段先吐出来**（【表情:xxx】），后端在流式过程中
切段、剥除标签并映射成结构化 {talk_emo, text}，前端实时换立绘。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LectureHistory
from ..schemas import LectureChatIn
from . import llm

logger = logging.getLogger("lecture_service")

# 表情标签正则：【表情:xxx】（冒号支持中英文），标签后跟正文
_EMO_TAG_RE = re.compile(r"【表情[:：]\s*([^】]+?)\s*】")

# 讲师合法表情集合（不在集合内一律回退默认讲解）
_KNOWN_EMO = {"jiangjie", "kaixin", "sikao", "yansutixing", "shengqi"}

# 多轮记忆：只回放入口最近的轮数（user+assistant 各算一轮，故乘 2）
_MAX_TURNS = 12


# ---------- 持久化读写（lecture_history 表）----------

def _query_history(db: Session, user_id: int, script_id: int) -> list[LectureHistory]:
    return list(
        db.scalars(
            select(LectureHistory)
            .where(LectureHistory.user_id == user_id, LectureHistory.script_id == script_id)
            .order_by(LectureHistory.created_at, LectureHistory.id)
        )
    )


def _read_recent(db: Session, user_id: int, script_id: int, max_turns: int = _MAX_TURNS) -> list[dict]:
    """取最近若干轮（user/assistant 交替二元组），供构建多轮上下文。"""
    rows = _query_history(db, user_id, script_id)
    pairs = [
        {"role": r.role, "content": r.content}
        for r in rows
        if r.role in ("user", "assistant") and r.content
    ]
    return pairs[-max_turns * 2 :] if len(pairs) > max_turns * 2 else pairs


def _history_count(db: Session, user_id: int, script_id: int) -> int:
    return len(_query_history(db, user_id, script_id))


def _append_row(db: Session, user_id: int, script_id: int, role: str, content: str) -> None:
    db.add(LectureHistory(user_id=user_id, script_id=script_id, role=role, content=content))
    db.commit()


def clear_lecture_history(db: Session, user_id: int, script_id: int) -> None:
    """退出讲师模式时清空该剧本、该用户的讲师会话记忆。"""
    rows = _query_history(db, user_id, script_id)
    for r in rows:
        db.delete(r)
    db.commit()


# ---------- 文本/表情处理 ----------

def _clean_text(text: str) -> str:
    """剥掉表情标签与收尾分隔符，保留纯讲解文本（存历史用）。"""
    text = _EMO_TAG_RE.sub("", text)
    text = text.replace("──", "")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _normalize_emo(emo: str) -> str:
    emo = (emo or "").strip().lower()
    return emo if emo in _KNOWN_EMO else "jiangjie"


LECTURER_SYSTEM_PROMPT = """你是用户召唤的专属讲师——当用户在视觉小说学习过程中遇到疑难知识点时，会通过「讲师」按钮或测验中的「深度学习」按钮向你求助。你是一位老师，擅长用生活化的语言把复杂概念讲得通透。

【角色设定】
- 你说活带点口语化，偶尔用"你看啊""咱们想想""说白了就是"这类自然过渡。
- 绝不使用"首先、其次、最后""总而言之""综上所述"等结构化套话。

【讲解要求（必须全部满足）】
1. 拒绝AI腔：禁止使用"值得注意的是""我们不难发现""具有重要的意义""从某种程度上说"等书面化僵尸词，全部换成口语表达，比如"这里要留个心眼""有意思的地方来了""说白了就是"。
2. 用类比或故事引入：先拿学生日常生活里熟悉的事儿打比方，再自然过渡到知识点本身，不要直接下定义。
3. 拆解痛点：讲出这个知识点最容易踩的坑、最容易混淆的地方，要像在跟学生唠嗑一样提醒。
4. 举一个"笨例子"：用一个最简单、甚至有点笨拙的具体数字或生活场景代入计算/演示，让学生一眼看穿本质。
5. 即兴感：句子长短错落，偶尔用反问句（"对吧？""是不是这个理？"），允许出现"嗯""你看""好嘞"等口头禅，但要节制。
6. 结尾留钩子：最后用一句自然的话引出下一步或相关延伸，不做"总结陈词"。

【知识来源优先级】
1. 当前学习资料中提取的内容（你已阅读完用户上传的全部资料）。
2. 若开启了联网，还可结合检索到的网络摘要（标注"依据检索信息"）。
3. 若资料覆盖不足，调用你的通用知识库补充。

【表情实时标注（硬性要求）】
- 每说一段话，必须先写【表情:xxx】标签，紧接着才是正文。标签只能从以下选：
  jiangjie（正常讲解，默认）、kaixin（欢迎/肯定用户、用户听懂了）、
  sikao（组织回答/等待用户思考）、yansutixing（强调重点/警醒用户）、
  shengqi（用户方向错了，严肃纠正）
- 示例输出：
【表情:jiangjie】打个比方来讲，你可以把内存想象成一张书桌…
【表情:yansutixing】这里要留个心眼，关键是…

【输出格式】
- 一段话一个标签，段与段之间用空行分隔；不要加任何标题、序号、分段标记（如"一、二、三"），只用换行分隔自然段落。
- 讲解内容整体控制在 300-500 字，不说与答疑无关的话。
- 回答结尾写一行「──」收尾，方便前端判断回答已结束。
"""


def _build_user_message(
    payload: LectureChatIn,
    source_text: str,
    include_source: bool,
    web_snippets: list[str],
) -> str:
    """组装讲师本轮的提问请求。

    include_source=False 用于多轮后续提问：资料已作为首轮锚点注入过一次，
    之后不再重复把整段资料塞进本轮，避免每轮 token 翻倍。
    web_snippets：联网搜索命中片段，附加供讲师参考；无结果为空。
    """
    parts = []
    if payload.context:
        parts.append(f"【当前上下文】{payload.context}")
    parts.append(f"【用户问题】{payload.question}")
    if include_source and source_text:
        parts.append(f"\n【学习资料片段（供参考，只取前6000字）】\n{source_text[:6000]}")
    if web_snippets:
        parts.append("\n【联网检索摘要（供参考，依据检索信息）】\n" + "\n".join(f"- {s}" for s in web_snippets))
    return "\n".join(parts)


def chat_stream(
    api_base: str,
    api_key: str,
    model: str,
    payload: LectureChatIn,
    source_text: str,
    use_web_search: bool = False,
    db: Optional[Session] = None,
    user_id: int = 1,
    thinking_level: str = "high",
) -> Iterator[dict]:
    """讲师流式作答：边接收 LLM 增量边切段，逐段产出 {talk_emo, text}。

    切段策略：累加字符 → 一旦发现完整「【表情:xxx】」标签，就把标签前的
    正文按上一段表情吐出，并切换当前表情；流结束时把剩余正文吐出。
    若模型漏标（少数情况），按段落（连续双换行）兜底切段，保证前端仍是
    逐段流式而非一次性整段。

    记忆：读取 lecture_history 表最近 N 轮作为多轮上下文；本轮 user 提问
    与 assistant 完整回答在流结束后落库持久化。

    引擎：走 llm 路由层（短任务 → 本地 Qwen 优先，云端兜底）。每段附带 engine
    字段，前端可据此标注「本地离线模型作答」，这也是论文分引擎延迟的采集点。
    """
    ctx = llm.RouteCtx()

    # 联网搜索：命中则附加片段供参考（无结果自动退化）
    web_snippets: list[str] = []
    if use_web_search and payload.question.strip():
        from . import search

        web_snippets = search.try_search(payload.question)

    # 资料片段：由路由层按「本轮用户问题」从本地知识库检索得到（小而聚焦），
    # 因此每一轮都注入相关片段作为依据（片段几百字，不再像过去只首轮塞整篇
    # 造成多轮 token 翻倍）。
    user_msg = _build_user_message(payload, source_text, include_source=bool(source_text), web_snippets=web_snippets)

    # 取「本轮之前」的最近历史，再记本轮提问入库（回答在流结束后补上）
    past_history = _read_recent(db, user_id, payload.script_id) if db is not None else []
    if db is not None:
        _append_row(db, user_id, payload.script_id, "user", user_msg)

    full_text_chunks: list[str] = []
    buf = ""                       # 已接收未切完的全部字符
    cursor = 0                     # 已消耗到 buf 的位置
    current_emo = "jiangjie"
    # 路由层此刻会选哪个引擎（只预测不调用），随每段下发给前端做「本地/云端」标注
    engine_used = llm.resolve_engine("lecture", api_key)

    try:
        for delta in llm.route_stream(
            api_base=api_base, api_key=api_key, model=model,
            system=LECTURER_SYSTEM_PROMPT,
            user=user_msg,
            history=past_history,   # 多轮记忆：system + 最近历史 + 本轮提问
            task="lecture", max_tokens=2048, timeout=300, ctx=ctx,
            reasoning_effort=thinking_level,
        ):
            full_text_chunks.append(delta)
            buf += delta

            # 1) 找本次新增范围内完整的【表情:xxx】标签并切段
            for m in _EMO_TAG_RE.finditer(buf):
                if m.start() < cursor:
                    continue  # 已消费过的标签
                pre = buf[cursor : m.start()].strip()
                if pre:
                    yield {"talk_emo": current_emo, "text": pre, "engine": engine_used}
                current_emo = _normalize_emo(m.group(1))
                cursor = m.end()
            # 2) 漏标兜底：超过 220 字的连续正文按【段落边界】切
            tail = buf[cursor:]
            if len(tail) > 220:
                cut_at = tail.rfind("\n\n")
                if cut_at >= 0 and not _EMO_TAG_RE.search(tail[cut_at:]):
                    yield {"talk_emo": current_emo, "text": tail[:cut_at], "engine": engine_used}
                    cursor += cut_at

        # 3) 流结束：吐出剩余
        tail = buf[cursor:].strip()
        if tail:
            yield {"talk_emo": current_emo, "text": tail, "engine": engine_used}
    except Exception as exc:  # 网络/密钥等异常：不阻断前端，吐一条提示
        logger.warning("讲师流式调用失败：%s", exc)
        # 有本地模型时，中断不等于「没法用了」——提示用户可继续用离线模型提问
        tip = ("（本次联网作答中断；已装本地离线模型，可再问一次让我用本地模型作答。）"
               if llm.local_available()
               else "（讲师说话似乎中断了，请检查网络或稍后再问一次。）")
        yield {"talk_emo": "sikao", "text": tip, "engine": engine_used}

    if ctx.result is not None:
        logger.info("讲师作答完成 engine=%s latency=%dms first_token=%dms degraded=%s",
                    ctx.result.engine, ctx.result.latency_ms,
                    ctx.result.first_token_ms, ctx.result.degraded)

    # 存完整回答进历史（剥标签、去收尾符）
    if db is not None:
        full_raw = "".join(full_text_chunks)
        _append_row(db, user_id, payload.script_id, "assistant", _clean_text(full_raw))
