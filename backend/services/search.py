"""内置联网搜索兜底：DuckDuckGo Instant Answer（免费、无需 Key）。

职责：讲师开启「联网搜索」时，把用户问题提交给 DuckDuckGo Instant Answer API，
取摘要/相关话题文本作为「联网参考片段」附加到讲师上下文。

兜底策略：任何异常（网络、超时、无结果、空摘要）都返回 []，
上层据此退化为「仅资料 + 通用知识」，绝不阻断讲师回答。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("search")

# DuckDuckGo Instant Answer（免费无 Key）
_DDG_ENDPOINT = "https://api.duckduckgo.com/"
_TIMEOUT = 8  # 秒（短超时，避免拖慢讲师首轮应答）


def try_search(query: str, max_items: int = 3) -> list[str]:
    """对 query 做一次联网搜索，返回最多 max_items 条摘要文本。

    失败/无结果一律返回 []（兜底），不抛出异常。
    """
    if not query or not query.strip():
        return []
    try:
        import requests

        r = requests.get(
            _DDG_ENDPOINT,
            params={"q": query.strip(), "format": "json", "no_html": 1},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # 网络 / 超时 / 非 JSON 均兜底
        logger.warning("联网搜索不可用（已退化为资料+通用知识）：%s", exc)
        return []

    snippets: list[str] = []
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        snippets.append(abstract)

    # 相关话题：扁平化递归收集（Instant Answer 的 RelatedTopics 是数组，可能含嵌套）
    def collect(topics: list, out: list[str]) -> None:
        for t in topics or []:
            if isinstance(t, dict):
                txt = (t.get("Text") or "").strip()
                if txt:
                    out.append(txt)
                elif isinstance(t.get("Topics"), list):
                    collect(t["Topics"], out)
            elif isinstance(t, str) and t.strip():
                out.append(t.strip())

    collect(data.get("RelatedTopics") or [], snippets)

    # 去重 + 截断过长片段
    seen = set()
    result: list[str] = []
    for s in snippets:
        if s in seen:
            continue
        seen.add(s)
        result.append(s[:300])
        if len(result) >= max_items:
            break
    logger.info("联网搜索命中 %d 条（query=%s）", len(result), query[:40])
    return result
