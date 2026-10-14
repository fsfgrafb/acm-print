import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain import selected_pages, settings
from ..errors import AppError
from ..models import Blob, Document, Grant, RenderPlan, SystemState
from ..security import Actor, current_actor
from ..services.documents import plan_storage_key
from ..services.storage import ensure_space, resolve, store_blob, temp_path

router = APIRouter()
EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".txt",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}


def authorized_document(db, actor, document_id):
    document = db.get(Document, document_id)
    grant = db.scalar(
        select(Grant).where(Grant.document_id == document_id, Grant.subject_id == actor.subject.id)
    )
    if not document or (not actor.admin and not grant):
        raise AppError("not_found", "文件不存在", 404)
    if not grant:
        grant = db.scalar(select(Grant).where(Grant.document_id == document_id).order_by(Grant.created_at))
    if not grant:
        raise AppError("not_found", "文件不存在", 404)
    return document, grant


def document_json(document, grant):
    return {
        "id": str(document.id),
        "filename": grant.filename,
        "status": document.status,
        "page_count": document.page_count,
        "error_code": document.error_code,
    }


@router.post("/files")
def upload(file: UploadFile, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    filename = (file.filename or "file").replace("\\", "/").split("/")[-1][:255]
    ext = Path(filename).suffix.lower()
    if ext not in EXTENSIONS:
        raise AppError("unsupported_format", "不支持此文件格式")
    limits = settings(db.get(SystemState, 1))
    # Coordinate upload admission across processes; bytes are checked while streaming.
    db.execute(text("SELECT pg_advisory_xact_lock(60101)"))
    existing_size = (
        db.execute(
            select(Blob.byte_size)
            .join(Document, Document.original_blob_id == Blob.id)
            .join(Grant, Grant.document_id == Document.id)
            .where(Grant.subject_id == actor.subject.id, Document.status != "ready")
        )
        .scalars()
        .all()
    )
    budget = limits["temporary_budget_mib"] * 1048576 - sum(existing_size)
    max_bytes = min(limits["max_file_mib"] * 1048576, budget)
    path, size = temp_path(ext), 0
    try:
        with path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise AppError("file_too_large", "文件或临时上传预算超过上限", 413)
                ensure_space(limits, len(chunk))
                output.write(chunk)
        if not size:
            raise AppError("empty_file", "文件为空")
        blob = store_blob(db, path)
        document = Document(original_blob_id=blob.id, source_ext=ext)
        db.add(document)
        db.flush()
        grant = Grant(subject_id=actor.subject.id, document_id=document.id, filename=filename)
        db.add(grant)
        db.commit()
        return document_json(document, grant)
    finally:
        path.unlink(missing_ok=True)


class Lookup(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/files/lookup")
def lookup(body: Lookup, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = db.execute(
        select(Document, Grant)
        .join(Grant, Grant.document_id == Document.id)
        .join(Blob, Blob.id == Document.original_blob_id)
        .where(Grant.subject_id == actor.subject.id, Blob.sha256 == body.sha256, Document.status == "ready")
        .limit(1)
    ).first()
    return {"file": document_json(*row) if row else None}


@router.get("/files/{document_id}")
def file_status(document_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return document_json(*authorized_document(db, actor, document_id))


class PlanInput(BaseModel):
    document_id: uuid.UUID
    mode: Literal["all", "odd", "even", "custom"] = "all"
    expression: str = Field(default="", max_length=10000)
    orientation: Literal["portrait", "landscape"] = "portrait"
    scaling: Literal["actual", "fit", "75%", "50%", "25%"] = "actual"


@router.post("/render-plans")
def create_plan(body: PlanInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    document, _ = authorized_document(db, actor, body.document_id)
    if document.status != "ready":
        raise AppError("file_not_ready", "文件尚未准备完成", 409)
    limits = settings(db.get(SystemState, 1))
    try:
        pages = selected_pages(body.mode, body.expression, document.page_count, limits["max_plan_pages"])
    except ValueError as exc:
        raise AppError("invalid_pages", str(exc)) from exc
    from ..adapters import adapter

    geometry = adapter().capabilities(body.orientation)["geometry"]
    blob = db.get(Blob, document.pdf_blob_id)
    key = plan_storage_key(blob.sha256, pages, geometry, body.scaling)
    cached = resolve(key).is_file()
    if cached:
        existing = db.scalar(select(RenderPlan).where(
            RenderPlan.owner_id == actor.subject.id,
            RenderPlan.document_id == document.id,
            RenderPlan.orientation == body.orientation,
            RenderPlan.storage_key == key,
            RenderPlan.status == "ready",
        ).limit(1))
        if existing:
            return plan_json(existing)
    plan = RenderPlan(
        owner_id=actor.subject.id,
        document_id=document.id,
        page_numbers=pages,
        orientation=body.orientation,
        scaling=body.scaling,
        geometry=geometry,
        status="ready" if cached else "processing",
        storage_key=key if cached else None,
    )
    db.add(plan)
    db.commit()
    return plan_json(plan)


def authorized_plan(db, actor, plan_id):
    plan = db.get(RenderPlan, plan_id)
    if not plan or (plan.owner_id != actor.subject.id and not actor.admin):
        raise AppError("not_found", "预览不存在", 404)
    authorized_document(db, actor, plan.document_id)
    return plan


def plan_json(plan):
    return {
        "id": str(plan.id),
        "document_id": str(plan.document_id),
        "status": plan.status,
        "page_numbers": plan.page_numbers,
        "orientation": plan.orientation,
        "scaling": plan.scaling,
        "geometry": plan.geometry,
        "error_code": plan.error_code,
    }


@router.get("/render-plans/{plan_id}")
def get_plan(plan_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return plan_json(authorized_plan(db, actor, plan_id))


@router.get("/render-plans/{plan_id}/pdf")
def plan_pdf(plan_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    plan = authorized_plan(db, actor, plan_id)
    if plan.status != "ready":
        raise AppError("plan_not_ready", "预览尚未准备完成", 409)
    return FileResponse(
        resolve(plan.storage_key),
        media_type="application/pdf",
        filename="print.pdf",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
