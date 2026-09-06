"""本地知识库（纯离线 RAG）—— 上传即入库、判题/讲解按需检索。

设计目标：
- 上传一份文档时，把其解析文本切成块并落盘到项目 knowledge/kb_{doc_id}/，
  之后判题与讲师讲解不再把「整篇资料」喂给本地模型，而是先按问题用轻量
  关键词打分（类 BM25）召回最相关的几段，再拼接成片段上下文。
- 纯标准库实现，零第三方依赖、纯离线；chunks 落盘 JSON，重启免重建、懒加载缓存。

目录（均在本地项目内）：
    <project_root>/knowledge/kb_{doc_id}/meta.json    文档元信息
    <project_root>/knowledge/kb_{doc_id}/chunks.json  切块数组
    <project_root>/knowledge/kb_{doc_id}/index.json   词频/DF 预计算（加速检索）
"""

from __future__ import annotations

import json
import math
import re
import threading
from pathlib import Path

# 分块参数
CHUNK_TARGET = 400          # 每块目标字符数
CHUNK_MAX = 600             # 单块上限（避免超模型上下文）
CHUNK_MIN = 200             # 过小并入前块
OVERLAP = 60                # 相邻块重叠字符（避免切断知识点）
# 检索参数
RETRIEVE_DEFAULT_TOP_K = 4

# 中文轻量切词：取 2~4 字滑窗 + 去停用词。BM25 的 term 用 2/3-gram 即可。
_STOP = set(
    "的了在是我和你他是这个与就都而及或一个也不把被对于从到当中非常主要进行及其以"
    "为因此所以然而并且或者关于应该可以需要如果要是这些那些什么怎样怎么为什么如何"
    "那么也就是说什么叫做例如比如以及包括因为所以由于"
)

_DOC_ID_RE = re.compile(r"[^\w\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """极简中文切词：清洗后取 2~4 字滑窗 term。"""
    cleaned = _DOC_ID_RE.sub("", text)
    if not cleaned:
        return []
    tokens: list[str] = []
    for size in (4, 3, 2):
        for i in range(0, len(cleaned) - size + 1, 1):
            if size == 4 and i % 2:
                continue  # 稀疏采样降低 term 数，保持召回
            tok = cleaned[i : i + size]
            if tok not in _STOP and not tok.isdigit():
                tokens.append(tok)
    return tokens


class KbMeta:
    """knowledge/kb_{doc_id} 下的元信息（dataclass 语义的简单封装）。"""

    def __init__(self, doc_id: int, filename: str, chunk_count: int, source_chars: int):
        self.doc_id = doc_id
        self.filename = filename
        self.chunk_count = chunk_count
        self.source_chars = source_chars

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "chunk_count": self.chunk_count,
            "source_chars": self.source_chars,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KbMeta":
        return cls(d["doc_id"], d.get("filename", ""), d.get("chunk_count", 0), d.get("source_chars", 0))


# —— 每文档内存缓存（索引惰性加载一次，多线程加锁）——
_cache_lock = threading.Lock()
_index_cache: dict[int, "_KbIndex"] = {}


class _KbIndex:
    """一块知识库的内存态索引：块文本 + BM25 统计（df / 每块词频）。"""

    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self.doc_tokens: list[list[str]] = [_tokenize(c) for c in chunks]
        self.doc_len = [len(t) for t in self.doc_tokens]
        # document frequency
        self.df: dict[str, int] = {}
        for toks in self.doc_tokens:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.n = len(chunks)
        self.avg_len = (sum(self.doc_len) / self.n) if self.n else 0.0


def _clean_text(content: str) -> str:
    """清洗：折叠空白、去控制字符、合并空行。"""
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)
    lines = [ln.strip() for ln in content.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _chunk_text(text: str) -> list[str]:
    """按段落分块，目标 300~500 字、重叠 OVERLAP。"""
    paras = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        # 段落过长则内部再按句切
        while len(p) > CHUNK_MAX:
            cut = p[:CHUNK_MAX]
            p = p[CHUNK_MAX:]
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(cut)
        if not buf:
            buf = p
        elif len(buf) + len(p) + 1 <= CHUNK_TARGET:
            buf += "\n" + p
        else:
            chunks.append(buf)
            # 带重叠续接：取 buf 末尾 OVERLAP 字与新段拼
            buf = (buf[-OVERLAP:] if len(buf) > OVERLAP else "") + p
    if buf:
        chunks.append(buf)
    # 过小块并入前一块
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < CHUNK_MIN and len(merged[-1]) < CHUNK_MAX * 1.5:
            merged[-1] += "\n" + c
        else:
            merged.append(c)
    return [c for c in merged if c.strip()]


def _kb_dir(kb_root: Path, doc_id: int) -> Path:
    return kb_root / f"kb_{doc_id}"


def build_kb(doc_id: int, filename: str, content: str, kb_root: Path) -> KbMeta:
    """上传解析后调用一次：切块 + 落盘 meta/chunks/index，并预热内存索引。

    Returns: KbMeta（含 chunk_count）。
    """
    cleaned = _clean_text(content)
    chunks = _chunk_text(cleaned)
    d = _kb_dir(kb_root, doc_id)
    d.mkdir(parents=True, exist_ok=True)

    meta = KbMeta(doc_id, filename, len(chunks), len(cleaned))
    (d / "meta.json").write_text(
        json.dumps(meta.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    (d / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    # 预热索引（无块时也建空索引，保证后续 retrieve 不炸）
    with _cache_lock:
        _index_cache[doc_id] = _KbIndex(chunks)
    return meta


def _load_index(doc_id: int, kb_root: Path) -> "_KbIndex | None":
    with _cache_lock:
        idx = _index_cache.get(doc_id)
    if idx is not None:
        return idx
    d = _kb_dir(kb_root, doc_id)
    if not (d / "chunks.json").exists():
        return None
    try:
        chunks = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    idx = _KbIndex(chunks if isinstance(chunks, list) else [])
    with _cache_lock:
        _index_cache[doc_id] = idx
    return idx


def _bm25_score(idx: "_KbIndex", query_terms: list[str]) -> list[float]:
    """Okapi BM25（k1=1.5, b=0.75）逐块打分。"""
    k1, b = 1.5, 0.75
    n = idx.n
    avg = idx.avg_len or 1.0
    scores = [0.0] * n
    for qt in set(query_terms):
        df_q = idx.df.get(qt, 0)
        if df_q == 0:
            continue
        idf = math.log(1 + (n - df_q + 0.5) / (df_q + 0.5))
        for doc_i in range(n):
            tf = idx.doc_tokens[doc_i].count(qt)
            if not tf:
                continue
            dl = idx.doc_len[doc_i]
            denom = tf + k1 * (1 - b + b * dl / avg)
            scores[doc_i] += idf * (tf * (k1 + 1)) / denom
    return scores


def _substring_boost(idx: "_KbIndex", query: str) -> list[float]:
    """实词子串原文命中加权：题干里的考点词（如「细胞壁」「蒸腾作用」）若在
    资料里以整串出现，命中块应显著靠前。对中文教育资料召回提升明显。"""
    # 从 query 抽取长度 2~6 的候选实词串（非纯标点/停用起始）
    cands: set[str] = set()
    for size in (6, 5, 4, 3, 2):
        for i in range(0, len(query) - size + 1):
            sub = query[i : i + size]
            if sub and sub[0] not in _STOP and not _DOC_ID_RE.search(sub):
                cands.add(sub)
    boost = [0.0] * idx.n
    for c in cands:
        hits = [ci for ci, ck in enumerate(idx.chunks) if c in ck]
        # 出现该实词串的块给加权，越罕见越重
        w = 6.0 if len(c) >= 4 else (4.0 if len(c) == 3 else 2.0)
        for ci in hits:
            boost[ci] += w / (1.0 + idx.chunks[ci].count(c) * 0.5)
    return boost


def retrieve(doc_id: int, query: str, kb_root: Path, top_k: int = RETRIEVE_DEFAULT_TOP_K) -> list[dict]:
    """按 query 检索知识库，返回按原始顺序排列的命中块。

    Returns: [{chunk_index, text, score}]；无命中或库不存在返回 []（上层据此兜底）。
    """
    if not query or not query.strip():
        return []
    idx = _load_index(doc_id, kb_root)
    if idx is None or idx.n == 0:
        return []
    qterms = _tokenize(query)
    if not qterms:
        return []
    scores = _bm25_score(idx, qterms)
    # 叠加实词子串原文命中加权（增强中文考点召回）
    sub = _substring_boost(idx, query)
    total = [a + b for a, b in zip(scores, sub)]
    ranked = sorted(range(idx.n), key=lambda i: total[i], reverse=True)
    top = [i for i in ranked[:top_k] if total[i] > 0]
    if not top:
        return []
    top.sort()  # 按原文顺序还原，保证上下文连贯
    return [
        {"chunk_index": i, "text": idx.chunks[i], "score": round(total[i], 3)}
        for i in top
    ]


def get_meta(doc_id: int, kb_root: Path) -> KbMeta | None:
    """读取元信息（用于详情展示入库段数）；不存在返回 None。"""
    d = _kb_dir(kb_root, doc_id)
    if not (d / "meta.json").exists():
        return None
    try:
        return KbMeta.from_dict(json.loads((d / "meta.json").read_text(encoding="utf-8")))
    except Exception:
        return None


def drop_kb(doc_id: int, kb_root: Path) -> None:
    """删除文档时清掉该知识库目录与内存缓存。"""
    with _cache_lock:
        _index_cache.pop(doc_id, None)
    d = _kb_dir(kb_root, doc_id)
    if d.exists():
        for f in d.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass
