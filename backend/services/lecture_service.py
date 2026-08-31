"""讲师一对一辅导服务（需求：用户召唤讲师深入讲解疑难知识点）。

讲师是用户召唤型角色：进入后切换到「一对一辅导」模式，讲师基于已导入的
学习资料 + 通用知识 + （可选）网络信息实时作答，SSE 流式逐段返回，每段
带 talk_emo 表情标签，前端据此实时切换讲师立绘并打字机显示。

会话记忆：同一剧本的多轮问答需要连贯，讲师要记得用户说过什么。
这里用进程内内存字典 {script_id: history} 维护多轮上下文（进程重启即清空，
符合「教学会话是一次性的」定位，不留脏数据）。

关键设计：**表情标签由模型每段先吐出来**（【表情:xxx】），后端在流式过程中
切段、剥除标签并映射成结构化 {talk_emo, text}，前端实时换立绘。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

from ..schemas import LectureChatIn
from .script_engine import _LLMClient

logger = logging.getLogger("lecture_service")

# 讲师会话记忆：{script_id: [{"role","content"}]}
_LECTURE_HISTORY: dict[int, list[dict]] = {}

# 表情标签正则：【表情:jiangjie】（冒号支持中英文），标签后跟正文
_EMO_TAG_RE = re.compile(r"【表情[:：]\s*([^】]+?)\s*】")
# 段界：标签之间往往以空行分隔，正文段落不应再被拆散
_PARAGRAPH_BREAK = "\n"

# 讲师合法表情集合（不在集合内一律回退默认讲解）
_KNOWN_EMO = {"jiangjie", "kaixin", "sikao", "yansutixing", "shengqi"}


def lecture_history(script_id: int) -> list[dict]:
    """取某剧本的讲师会话历史，不存在则返回空列表。"""
    return _LECTURE_HISTORY.get(script_id, [])


def clear_lecture_history(script_id: int) -> None:
    """退出讲师模式时清空该剧本的会话记忆。"""
    _LECTURE_HISTORY.pop(script_id, None)


def _append(script_id: int, role: str, content: str) -> None:
    _LECTURE_HISTORY.setdefault(script_id, []).append({"role": role, "content": content})


def _trim_history(history: list[dict], max_turns: int = 12) -> list[dict]:
    """控制多轮上下文长度：只保留最近 max_turns 轮，避免 token 无限增长。"""
    return history[-max_turns * 2 :] if len(history) > max_turns * 2 else history


def _clean_text(text: str) -> str:
    """剥掉表情标签与收尾分隔符，保留纯讲解文本（存历史用）。"""
    text = _EMO_TAG_RE.sub("", text)
    text = text.replace("──", "")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _normalize_emo(emo: str) -> str:
    emo = (emo or "").strip().lower()
    return emo if emo in _KNOWN_EMO else "jiangjie"


LECTURER_SYSTEM_PROMPT = """你是用户召唤的专属讲师——当用户在视觉小说学习过程中遇到疑难知识点时，会通过「讲师」按钮或测验中的「深度学习」按钮向你求助。你的职责是：以最清晰、最易懂的方式，帮助用户彻底理解当前卡住的知识点。

【你的性格】
- 专业但有亲和力，不居高临下
- 讲解耐心，善于用类比和例子说明抽象概念
- 会观察用户的反馈（如"听懂了"），据此调整讲解深度
- 面对复杂问题时，会先拆解再逐一讲解

【你的说话风格】
- 语气温和但专业，用词精准
- 善用"打个比方来说…"、"你可以这样理解…"、"关键在于…"等引导性表达
- 讲解时由浅入深，先给直觉理解，再给严谨表述
- 你已阅读完用户上传的全部学习资料，优先基于资料内容回答

【知识来源优先级】
1. 优先使用当前学习资料中提取的内容（你已阅读完用户上传的全部资料）
2. 若资料覆盖不足，可以调用你的通用知识库补充
3. 若启用联网搜索，你还可以整合网络最新信息，但须标注来源

【表情实时标注（硬性要求）】
- 每说一段话，必须先写【表情:xxx】标签，紧接着才是正文。标签只能从以下选：
  jiangjie（正常讲解，默认）、kaixin（欢迎/肯定用户、用户听懂了）、
  sikao（组织回答/等待用户思考）、yansutixing（强调重点/警醒用户）、
  shengqi（用户方向错了，严肃纠正）
- 示例输出：
【表情:jiangjie】打个比方来说，你可以把内存想象成一张书桌…
【表情:yansutixing】关键在于，这里的重点是…

【输出格式】
- 一段话一个标签，段与段之间用空行分隔。
- 回答结尾写一行「──」收尾，方便前端判断回答已结束。
"""


def _build_user_message(payload: LectureChatIn, source_text: str, include_source: bool = True) -> str:
    """组装讲师本轮的提问请求。

    include_source=False 用于多轮后续提问：资料已作为首轮锚点注入过一次，
    之后不再重复把整段资料塞进本轮，避免每轮 token 翻倍。
    """
    parts = []
    if payload.context:
        parts.append(f"【当前上下文】{payload.context}")
    parts.append(f"【用户问题】{payload.question}")
    if include_source and source_text:
        parts.append(f"\n【学习资料片段（供参考，只取前6000字）】\n{source_text[:6000]}")
    return "\n".join(parts)


def chat_stream(
    api_base: str,
    api_key: str,
    model: str,
    payload: LectureChatIn,
    source_text: str,
) -> Iterator[dict]:
    """讲师流式作答：边接收 LLM 增量边切段，逐段产出 {talk_emo, text}。

    切段策略：累加字符 → 一旦发现完整「【表情:xxx】」标签，就把标签前的
   正文按上一段表情吐出，并切换当前表情；流结束时把剩余正文吐出。
    若模型漏标（少数情况），按段落（连续双换行）兜底切段，保证前端仍是
    逐段流式而非一次性整段。
    """
    client = _LLMClient(api_base, api_key, model, max_tokens=2048, timeout=300)
    # 首轮时把资料片段一并注入（讲师首次锚定学习内容）；
    # 之后的历史已经带过资料，不再重复塞，避免每轮 token 翻倍。
    is_first_turn = payload.script_id not in _LECTURE_HISTORY
    user_msg = _build_user_message(payload, source_text, include_source=is_first_turn)

    # 取「本轮之前」的历史快照（只取最近几轮，控制 token 增长），
    # 再记本轮提问入完整历史（回答会在流结束后补上）。
    # 注意：请求里不能把刚记的本轮提问再重复塞一遍，否则模型会看到两遍问题。
    past_history = _trim_history(lecture_history(payload.script_id))
    _append(payload.script_id, "user", user_msg)

    full_text_chunks: list[str] = []
    buf = ""                       # 已接收未切完的全部字符
    cursor = 0                     # 已消耗到 buf 的位置
    current_emo = "jiangjie"

    try:
        for delta in client.stream_chat(
            system_prompt=LECTURER_SYSTEM_PROMPT,
            user_prompt=user_msg,
            history=past_history,   # 多轮记忆：system + 最近历史 + 本轮提问
        ):
            full_text_chunks.append(delta)
            buf += delta

            # 1) 找本次新增范围内完整的【表情:xxx】标签并切段
            for m in _EMO_TAG_RE.finditer(buf):
                if m.start() < cursor:
                    continue  # 已消费过的标签
                pre = buf[cursor : m.start()].strip()
                if pre:
                    yield {"talk_emo": current_emo, "text": pre}
                current_emo = _normalize_emo(m.group(1))
                cursor = m.end()
            # 2) 漏标兜底：超过 220 字的连续正文按【段落边界】切
            tail = buf[cursor:]
            if len(tail) > 220:
                # 只在明确的段落边界处切，避免把模型正在写的标签字头切坏
                cut_at = tail.rfind("\n\n")
                if cut_at >= 0 and not _EMO_TAG_RE.search(tail[cut_at:]):
                    yield {"talk_emo": current_emo, "text": tail[:cut_at]}
                    cursor += cut_at

        # 3) 流结束：吐出剩余
        tail = buf[cursor:].strip()
        if tail:
            yield {"talk_emo": current_emo, "text": tail}
    except Exception as exc:  # 网络/密钥等异常：不阻断前端，吐一条提示
        logger.warning("讲师流式调用失败：%s", exc)
        yield {
            "talk_emo": "sikao",
            "text": "（讲师说话似乎中断了，请检查网络或稍后再问一次。）",
        }

    # 存完整回答进历史（剥标签、去收尾符）
    full_raw = "".join(full_text_chunks)
    _append(payload.script_id, "assistant", _clean_text(full_raw))