"""文档路由：上传 Word/PDF、解析入库、列表、详情。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Document, Progress
from ..schemas import DocumentOut
from ..services.extractor import ExtractionError, extract_document, extract_title

logger = logging.getLogger("documents")
router = APIRouter(prefix="/api/documents", tags=["documents"])

# 上传大小上限 20MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件过大（上限 20MB）")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")

    try:
        content = extract_document(file.filename, data)
    except ExtractionError as exc:
        raise HTTPException(400, str(exc))

    if not content.strip():
        raise HTTPException(400, "无法从该文档提取到文本内容，请检查文件是否损坏或纯图片文档。")

    title = extract_title(file.filename)
    doc = Document(filename=file.filename, title=title, content=content)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    logger.info("已解析文档 %s（%d 字符）", file.filename, len(content))
    return _to_out(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Document).options(selectinload(Document.scripts)).order_by(Document.created_at.desc())
    ).all()
    return [_to_out(d) for d in rows]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    return _to_out(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """删除资料及其关联剧本与进度（瀑布式清理）。"""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    # SQLite 默认不启用外键级联，先手动清理剧本附属的进度记录，再删剧本与文档
    script_ids = [s.id for s in doc.scripts]
    if script_ids:
        db.query(Progress).filter(Progress.script_id.in_(script_ids)).delete(
            synchronize_session=False
        )
    db.delete(doc)   # relationship cascade 会连带删除 scripts
    db.commit()


def _to_out(doc: Document) -> DocumentOut:
    # 只回传前 200 字预览，避免整篇资料在前后端间重复传输
    scripts = sorted(doc.scripts, key=lambda s: s.id, reverse=True)
    latest = scripts[0] if scripts else None
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        title=doc.title,
        content_preview=doc.content[:200],
        created_at=doc.created_at.isoformat(),
        has_script=bool(scripts),
        latest_script_id=latest.id if latest else None,
    )