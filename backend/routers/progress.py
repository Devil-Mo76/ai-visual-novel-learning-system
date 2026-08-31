"""进度路由：自动保存（主槽0）、手动存档（槽1-9）、续播恢复、存档列表。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Document, Progress, Script
from ..schemas import ArchiveOut, ProgressOut, ProgressSaveIn

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.post("/save", response_model=ProgressOut)
def save_progress(payload: ProgressSaveIn, db: Session = Depends(get_db)):
    script = db.get(Script, payload.script_id)
    if script is None:
        raise HTTPException(404, "剧本不存在")

    # 同槽位只保留一份进度（自动槽会被每节点覆盖）
    existing = db.scalars(
        select(Progress).where(
            Progress.script_id == payload.script_id,
            Progress.slot == payload.slot,
        )
    ).first()
    if existing:
        existing.chapter_index = payload.chapter_index
        existing.step_index = payload.step_index
        row = existing
    else:
        row = Progress(
            script_id=payload.script_id,
            slot=payload.slot,
            chapter_index=payload.chapter_index,
            step_index=payload.step_index,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("/latest")
def latest_progress(db: Session = Depends(get_db)):
    """最近一次更新进度的信息，供「继续学习」直接跳转。"""
    row = db.scalars(
        select(Progress).order_by(Progress.updated_at.desc(), Progress.id.desc()).limit(1)
    ).first()
    if row is None:
        return {"exists": False}
    script = db.get(Script, row.script_id)
    return {
        "exists": True,
        "script_id": row.script_id,
        "slot": row.slot,
        "chapter_index": row.chapter_index,
        "step_index": row.step_index,
        "title": script.title if script else "",
        "background": (script.chapters[row.chapter_index]["background"] if script and row.chapter_index < len(script.chapters) and len(script.chapters[row.chapter_index].get("steps", [])) >= 0 else "客厅"),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/slots/{script_id}")
def list_slots(script_id: int, db: Session = Depends(get_db)):
    """给定剧本的全部存档槽位（主槽0 + 手动槽1-9）。"""
    rows = db.scalars(
        select(Progress).where(Progress.script_id == script_id).order_by(Progress.slot)
    ).all()
    return {"script_id": script_id, "slots": [_to_out(r) for r in rows]}


@router.get("/list", response_model=list[ArchiveOut])
def list_archive(db: Session = Depends(get_db)):
    """全部存档（含用户导入的资料名），供主菜单「读取存档」使用。
    每行存档标注其剧本关联文档（学习资料）的名称。"""
    rows = db.scalars(select(Progress).order_by(Progress.updated_at.desc(), Progress.id.desc())).all()
    out = []
    for r in rows:
        script = db.get(Script, r.script_id)
        title = ""
        if script:
            doc = db.get(Document, script.document_id)
            title = doc.title if doc else script.source
        out.append(ArchiveOut(
            script_id=r.script_id,
            slot=r.slot,
            chapter_index=r.chapter_index,
            step_index=r.step_index,
            updated_at=r.updated_at.isoformat(),
            document_title=title,
        ))
    return out


@router.delete("/{script_id}/{slot}")
def delete_progress(script_id: int, slot: int, db: Session = Depends(get_db)):
    """删除某个剧本的指定存档槽（slot=0 自动档，1-9 手动档）。返回受影响的记录数。"""
    deleted = db.scalars(
        select(Progress).where(
            Progress.script_id == script_id,
            Progress.slot == slot,
        )
    ).all()
    for row in deleted:
        db.delete(row)
    db.commit()
    return {"deleted": len(deleted)}


@router.get("/{script_id}", response_model=ProgressOut)
def get_progress(script_id: int, db: Session = Depends(get_db)):
    """读取该剧本最近一次进度（继续播放用）。"""
    row = db.scalars(
        select(Progress).where(Progress.script_id == script_id)
        .order_by(Progress.updated_at.desc(), Progress.id.desc()).limit(1)
    ).first()
    if row is None:
        return ProgressOut(
            script_id=script_id, slot=0, chapter_index=0, step_index=0,
            updated_at="",
        )
    return _to_out(row)


def _to_out(row: Progress) -> ProgressOut:
    return ProgressOut(
        script_id=row.script_id,
        slot=row.slot,
        chapter_index=row.chapter_index,
        step_index=row.step_index,
        updated_at=row.updated_at.isoformat(),
    )