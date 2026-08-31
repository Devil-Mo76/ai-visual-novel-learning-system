"""文档解析：从 .docx / .pdf 提取纯文本，并保留表格结构。

支持范围：
- .docx：python-docx 遍历 document.tables，将每个表格转换为标准 Markdown 表格，
  用【表格N】标记行嵌入正文相应位置 —— 防止学习资料中的表格数据凭空丢失。
- .pdf：优先 pdfplumber 结构化提取表格（page.extract_tables，返回二维数组），
  转为 Markdown 表格嵌入；未安装 pdfplumber 时回退 pypdf 页面纯文本（表格会被
  压平为文字，但正文与页面文本不会丢失，保证依赖缺失也能跑）。
- 未安装任何对应解析库时返回明确错误信息，避免答辩现场因缺依赖而白屏。
"""
from __future__ import annotations

import io


class ExtractionError(Exception):
    pass


def extract_document(filename: str, data: bytes) -> str:
    """根据扩展名分派解析，返回纯文本（含 Markdown 表格）。"""
    lower = filename.lower()
    if lower.endswith(".docx"):
        return _extract_docx(data)
    if lower.endswith(".pdf"):
        return _extract_pdf(data)
    raise ExtractionError(
        f"不支持的文件类型：{filename}（仅支持 .docx / .pdf）"
    )


def _rows_to_markdown(rows: list[list[str]]) -> str:
    """二维字符串数组 → 标准 Markdown 表格文本（表头 + 分隔行 + 数据行）。

    自动剔除全空行、按最大列宽补齐单元格，保证格式整洁、可直接被 AI 解读。
    """
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)

    def pad(r: list[str]) -> list[str]:
        return [((c or "").strip()) for c in r] + [""] * (ncol - len(r))

    grid = [pad(r) for r in rows]
    header, body = grid[0], grid[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * ncol) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ExtractionError("缺少依赖 python-docx，请执行：pip install python-docx")

    doc = Document(io.BytesIO(data))
    parts: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    # 表格：python-docx 合并单元格会在 row.cells 中重复同一对象，
    # 用元素身份去重后再转 Markdown，保证列宽对齐且不引入重复列。
    for idx, table in enumerate(doc.tables, start=1):
        rows: list[list[str]] = []
        for row in table.rows:
            cells, last_tc = [], None
            for cell in row.cells:
                if last_tc is not None and cell._tc is last_tc:
                    continue
                last_tc = cell._tc
                cells.append(cell.text)
            rows.append(cells)
        md = _rows_to_markdown(rows)
        if md:
            parts.append(f"\n【表格{idx}】\n{md}")

    return "\n".join(parts)


def _extract_pdf(data: bytes) -> str:
    # 优先 pdfplumber（结构化表格）；未安装则回退 pypdf 纯文本
    try:
        return _extract_pdf_plumber(data)
    except ImportError:
        return _extract_pdf_text_only(data)


def _extract_pdf_plumber(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise  # 让上层回退

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(text)
            for t_idx, table in enumerate(page.extract_tables() or [], start=1):
                rows = [[(c or "").strip() for c in row] for row in table]
                md = _rows_to_markdown(rows)
                if md:
                    parts.append(f"\n【表格{t_idx}】\n{md}")
    return "\n".join(parts)


def _extract_pdf_text_only(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractionError(
            "缺少 PDF 解析依赖，请执行：pip install pdfplumber（推荐）或 pip install pypdf"
        )

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_title(filename: str) -> str:
    """用文件名（去扩展名）作为初始标题。"""
    base = filename.rsplit(".", 1)[0]
    return base or filename