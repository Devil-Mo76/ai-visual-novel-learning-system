"""文档路由：上传 Word/PDF、解析入库、列表、详情。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user
from ..config import settings
from ..db import get_db
from ..models import Document, Progress, User
from ..schemas import DocumentOut
from ..services.extractor import ExtractionError, extract_document, extract_title
from ..services import knowledge_base

logger = logging.getLogger("documents")
router = APIRouter(prefix="/api/documents", tags=["documents"])

# 上传大小上限 20MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _get_owned_doc(db: Session, user, doc_id: int):
    """按归属校验取文档：必须属于当前用户，否则 404（多用户隔离）。"""
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(404, "文档不存在")
    return doc


def _user_upload_dir(user_id: int) -> Path:
    """该用户的原始文件上传根目录：uploads/u{user_id}/。"""
    d = Path(settings.uploads_dir) / f"u{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist_original_and_kb(doc: Document, raw: bytes) -> None:
    """上传后把原始文件落到本地 uploads/，并为其解析文本建立本地知识库。

    两步都做「尽力而为」：任一步失败只记日志，不阻断上传主流程
    （原始文本已存 DB，知识库检索失败时会回退到空片段 + 通用知识兜底）。
    """
    # 1) 原始文件落盘（去路径分隔符防穿越，保留扩展名）
    safe_name = doc.filename.replace("\\", "_").replace("/", "_")
    fdir = _user_upload_dir(doc.user_id)
    fpath = fdir / f"{doc.id}_{safe_name}"
    try:
        fpath.write_bytes(raw)
        doc.file_path = str(Path(f"u{doc.user_id}") / fpath.name)
    except OSError as exc:
        logger.warning("原始文件落盘失败 doc=%d: %s", doc.id, exc)
        doc.file_path = ""

    # 2) 建本地知识库（切块索引落到 knowledge/kb_{doc_id}/）
    try:
        meta = knowledge_base.build_kb(doc.id, doc.filename, doc.content, Path(settings.knowledge_dir))
        doc.chunk_count = meta.chunk_count
    except Exception as exc:  # noqa: BLE001 建库失败不阻断上传
        logger.warning("本地知识库建立失败 doc=%d: %s", doc.id, exc)
        doc.chunk_count = 0


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    doc = Document(user_id=user.id, filename=file.filename, title=title, content=content)
    db.add(doc)
    db.commit()          # 先落库拿到 doc.id
    db.refresh(doc)

    # 落盘原始文件 + 建立本地知识库（切块索引），回填 file_path / chunk_count
    _persist_original_and_kb(doc, data)
    db.commit()
    db.refresh(doc)
    logger.info("已解析文档 %s（%d 字符），知识库切块 %d", file.filename, len(content), doc.chunk_count)
    return _to_out(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Document)
        .where(Document.user_id == user.id)
        .options(selectinload(Document.scripts))
        .order_by(Document.created_at.desc())
    ).all()
    return [_to_out(d) for d in rows]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_owned_doc(db, user, doc_id)
    return _to_out(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除资料及其关联剧本与进度（瀑布式清理），并清掉本地知识库与原始文件。"""
    doc = _get_owned_doc(db, user, doc_id)
    # SQLite 默认不启用外键级联，先手动清理剧本附属的进度记录，再删剧本与文档
    script_ids = [s.id for s in doc.scripts]
    if script_ids:
        db.query(Progress).filter(Progress.script_id.in_(script_ids)).delete(
            synchronize_session=False
        )
    # 清理本地知识库目录（knowledge/kb_{doc_id}/）
    try:
        knowledge_base.drop_kb(doc_id, Path(settings.knowledge_dir))
    except Exception as exc:  # noqa: BLE001
        logger.warning("清理知识库失败 doc=%d: %s", doc_id, exc)
    # 删除该用户的原始上传文件（uploads/u{uid}/{file}）
    if doc.file_path:
        try:
            fp = Path(settings.uploads_dir) / doc.file_path
            if fp.exists():
                fp.unlink()
        except OSError as exc:
            logger.warning("删除原始文件失败 %s: %s", doc.file_path, exc)
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
        chunk_count=getattr(doc, "chunk_count", 0) or 0,
    )