import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import config
from ..db import get_db
from ..domain import ACTIVE_STATES, settings
from ..errors import AppError
from ..models import (
    Batch,
    Blob,
    Grant,
    History,
    Idempotency,
    PrintTask,
    RenderPlan,
    Subject,
    SubmitVisit,
    SystemState,
    now,
)
from ..security import Actor, current_actor
from ..services.storage import ensure_space, resolve
from .files import authorized_document, authorized_plan, document_json, plan_json

router = APIRouter()


def submit_statistics(db):
    return {
        "visit_count": db.scalar(select(SystemState.submit_visit_count).where(SystemState.id == 1)),
        "print_total_pages": db.scalar(select(func.coalesce(func.sum(History.total_pages), 0))),
    }


@router.get("/printing/statistics")
def printing_statistics(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return submit_statistics(db)


class VisitInput(BaseModel):
    visit_id: uuid.UUID


@router.post("/printing/visit")
def submit_visit(body: VisitInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    added = db.scalar(insert(SubmitVisit).values(id=body.visit_id, created_at=now())
                      .on_conflict_do_nothing(index_elements=[SubmitVisit.id]).returning(SubmitVisit.id))
    if added:
        db.execute(update(SystemState).where(SystemState.id == 1)
                   .values(submit_visit_count=SystemState.submit_visit_count + 1))
    db.commit()
    return submit_statistics(db)


@router.get("/printing/options")
def printing_options(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    limits = settings(db.get(SystemState, 1))
    return {key: limits[key] for key in ("max_copies", "max_batch_files", "max_file_mib")}


class BatchItem(BaseModel):
    plan_id: uuid.UUID
    copies: int = Field(ge=1, le=100)
    parent_task_id: uuid.UUID | None = None


class BatchInput(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    items: list[BatchItem] = Field(min_length=1, max_length=100)


@router.post("/print-batches")
def submit(body: BatchInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    digest = hashlib.sha256(
        json.dumps([item.model_dump(mode="json") for item in body.items], sort_keys=True).encode()
    ).hexdigest()
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"batch:{actor.subject.id}:{body.idempotency_key}"},
    )
    entry = db.get(Idempotency, (actor.subject.id, body.idempotency_key))
    if entry:
        if entry.digest != digest:
            raise AppError("idempotency_conflict", "同一操作键不能用于不同参数", 409)
        if not entry.batch_id:
            raise AppError("batch_removed", "原批次已清理，请发起新的打印操作", 410)
        return {"batch_id": str(entry.batch_id), "reused": True}
    limits = settings(db.get(SystemState, 1))
    if len(body.items) > limits["max_batch_files"] or any(
        i.copies > limits["max_copies"] for i in body.items
    ):
        raise AppError("batch_limit", "文件数量或份数超过系统上限")
    ensure_space(limits)
    # Serializes sequence allocation through commit, preserving accepted batch order.
    db.execute(text("SELECT pg_advisory_xact_lock(60102)"))
    batch = Batch(owner_id=actor.subject.id)
    db.add(batch)
    db.flush()
    for position, item in enumerate(body.items):
        plan = authorized_plan(db, actor, item.plan_id)
        if plan.owner_id != actor.subject.id or plan.status != "ready":
            raise AppError("plan_not_ready", "请先完成并确认本人预览", 409)
        from ..adapters import adapter

        if plan.geometry != adapter().capabilities(plan.orientation)["geometry"]:
            raise AppError("geometry_changed", "设备版面已变化，请重新预览", 409)
        document, grant = authorized_document(db, actor, plan.document_id)
        if document.status != "ready":
            raise AppError("file_not_ready", "文件尚未准备完成", 409)
        if item.parent_task_id:
            authorized_task(db, actor, item.parent_task_id)
        if not db.scalar(
            select(Grant).where(Grant.subject_id == actor.subject.id, Grant.document_id == document.id)
        ):
            db.add(Grant(subject_id=actor.subject.id, document_id=document.id, filename=grant.filename))
        db.add(
            PrintTask(
                batch_id=batch.id,
                position=position,
                document_id=document.id,
                plan_id=plan.id,
                copies=item.copies,
                filename=grant.filename,
                parent_task_id=item.parent_task_id,
            )
        )
    db.add(
        Idempotency(subject_id=actor.subject.id, key=body.idempotency_key, digest=digest, batch_id=batch.id)
    )
    db.commit()
    return {"batch_id": str(batch.id), "reused": False}


def authorized_task(db, actor, task_id, locked=False):
    query = select(PrintTask).where(PrintTask.id == task_id)
    task = db.scalar(query.with_for_update() if locked else query)
    batch = db.get(Batch, task.batch_id) if task else None
    if not task or (not actor.admin and batch.owner_id != actor.subject.id):
        raise AppError("not_found", "任务不存在", 404)
    return task


@router.get("/queue")
def queue(
    page: Annotated[int, Query(ge=1)] = 1,
    scope: str = "active",
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    if scope not in {"active", "history"}:
        raise AppError("invalid_scope", "队列范围错误")
    query = select(PrintTask, Batch, Subject, RenderPlan).join(Batch, Batch.id == PrintTask.batch_id)
    query = query.join(Subject, Subject.id == Batch.owner_id).join(
        RenderPlan, RenderPlan.id == PrintTask.plan_id
    )
    if scope == "active":
        query = query.where(PrintTask.state.in_(ACTIVE_STATES))
    else:
        query = query.join(History, History.task_id == PrintTask.id)
    rows = db.execute(
        query.order_by(Batch.sequence.desc(), PrintTask.position).offset((page - 1) * 30).limit(31)
    ).all()
    items = []
    for task, batch, subject, plan in rows[:30]:
        mine = batch.owner_id == actor.subject.id
        item = {
            "id": str(task.id),
            "student_id": subject.student_id,
            "state": task.state,
            "created_at": task.created_at.isoformat(),
            "submitted_at": task.submitted_at,
            "total_pages": len(plan.page_numbers) * task.copies,
            "mine": mine,
            "can_cancel": (mine or actor.admin)
            and (
                task.state in {"queued", "submitting"}
                or (task.state in {"submitted", "printing"} and config().printer.cancel_verified)
            ),
            "can_download": (mine or actor.admin) and task.submitted_at is not None,
        }
        if actor.admin:
            item["filename"] = task.filename
            item["plan_id"] = str(plan.id)
        items.append(item)
    state = db.get(SystemState, 1)
    device = (
        state.device
        if state.device_checked_at
        and (now() - state.device_checked_at).total_seconds() < max(30, settings(state)["poll_seconds"] * 3)
        else {"available": False, "blocked": True, "message": "打印进程尚未连接或状态已过期"}
    )
    contact = None
    admin = db.get(Subject, state.admin_subject_id)
    if admin:
        contact = {"email": admin.email, "phone": admin.phone}
    return {"items": items, "has_more": len(rows) > 30, "paused": state.paused, "device": device, "admin_contact": contact}


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    task = authorized_task(db, actor, task_id, locked=True)
    if task.state == "queued":
        task.state = "cancelled"
    elif task.state in {"submitting", "submitted", "printing", "cancelling"}:
        from ..config import config

        if task.state != "submitting" and not config().printer.cancel_verified:
            raise AppError("cancel_not_supported", "在印取消尚未通过设备验收", 409)
        task.cancel_requested = True
    else:
        raise AppError("cannot_cancel", "当前状态不能取消", 409)
    task.updated_at = now()
    db.commit()
    return {"state": task.state, "cancel_requested": task.cancel_requested}


@router.get("/tasks/{task_id}/resubmit-plan")
def resubmit(task_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    task = authorized_task(db, actor, task_id)
    document, grant = authorized_document(db, actor, task.document_id)
    return {
        "file": document_json(document, grant),
        "plan": plan_json(db.get(RenderPlan, task.plan_id)),
        "copies": task.copies,
        "parent_task_id": str(task.id),
    }


@router.get("/tasks/{task_id}/original")
def download_original(
    task_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)
):
    task = authorized_task(db, actor, task_id)
    if not task.submitted_at:
        raise AppError("history_not_available", "尚未产生成功提交历史", 409)
    document, _ = authorized_document(db, actor, task.document_id)
    return FileResponse(
        resolve(db.get(Blob, document.original_blob_id).storage_key),
        filename=task.filename,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/tasks/{task_id}/pdf")
def download_pdf(task_id: uuid.UUID, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    task = authorized_task(db, actor, task_id)
    if not task.submitted_at:
        raise AppError("history_not_available", "尚未产生成功提交历史", 409)
    plan = db.get(RenderPlan, task.plan_id)
    return FileResponse(
        resolve(plan.storage_key),
        filename="print.pdf",
        media_type="application/pdf",
        headers={"Cache-Control": "private, no-store"},
    )
