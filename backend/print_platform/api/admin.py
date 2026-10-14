import csv
import hashlib
import io
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, UploadFile
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import config
from ..db import get_db
from ..domain import SETTINGS, four_years, settings, validate_email, validate_phone
from ..errors import AppError
from ..models import History, ImportCommit, Subject, SystemState, now
from ..security import Actor, admin_actor, passwords, revoke, verify
from ..services.identity import parse_import, transfer

router = APIRouter(prefix="/admin")


@router.get("/students")
def students(
    page: Annotated[int, Query(ge=1)] = 1, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(Subject).order_by(Subject.created_at.desc()).offset((page - 1) * 30).limit(31)
    ).all()
    return {
        "items": [
            {
                "id": str(s.id),
                "student_id": s.student_id,
                "email": s.email,
                "phone": s.phone,
                "banned": s.banned,
                "admin": s.id == actor.subject.id,
                "created_at": s.created_at,
                "expires_at": s.expires_at,
            }
            for s in rows[:30]
        ],
        "has_more": len(rows) > 30,
    }


def import_data(file):
    data = file.file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise AppError("csv_too_large", "CSV 最大 2 MiB", 413)
    return data


@router.post("/import/preview")
def import_preview(file: UploadFile, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    rows = parse_import(import_data(file))
    existing = set(db.scalars(select(Subject.student_id)).all())
    for row in rows:
        if row["status"] == "new" and row["student_id"] in existing:
            row.update(status="skipped", reason="已存在")
    return {"rows": rows}


@router.post("/import/commit")
def import_commit(
    file: UploadFile,
    key: str = Query(min_length=8, max_length=128),
    actor: Actor = Depends(admin_actor),
    db: Session = Depends(get_db),
):
    data = import_data(file)
    digest = hashlib.sha256(data).hexdigest()
    return commit_rows(db, actor, key, digest, parse_import(data))


def commit_rows(db, actor, key, digest, rows):
    db.execute(text("SELECT pg_advisory_xact_lock(60103)"))
    old = db.get(ImportCommit, (actor.subject.id, key))
    if old:
        if old.digest != digest:
            raise AppError("idempotency_conflict", "导入操作键冲突", 409)
        return old.result
    existing = set(db.scalars(select(Subject.student_id)).all())
    result = {"added": 0, "skipped": 0, "invalid": 0}
    created = now()
    for row in rows:
        if row["status"] == "invalid":
            result["invalid"] += 1
        elif row["status"] == "skipped" or row["student_id"] in existing:
            result["skipped"] += 1
        else:
            identity = row["student_id"]
            db.add(
                Subject(
                    student_id=identity,
                    password_hash=passwords.hash(identity),
                    email=row["email"],
                    phone=row["phone"],
                    created_at=created,
                    expires_at=four_years(created),
                )
            )
            existing.add(identity)
            result["added"] += 1
    db.add(ImportCommit(owner_id=actor.subject.id, key=key, digest=digest, result=result))
    db.commit()
    return result


class MemberUpdate(BaseModel):
    expires_at: AwareDatetime | None = None
    banned: bool | None = None
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        return validate_email(value) if value is not None else None

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value):
        return validate_phone(value) if value is not None else None


@router.patch("/students/{subject_id}")
def update_member(
    subject_id: uuid.UUID,
    body: MemberUpdate,
    actor: Actor = Depends(admin_actor),
    db: Session = Depends(get_db),
):
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    subject = db.scalar(select(Subject).where(Subject.id == subject_id).with_for_update())
    if not subject:
        raise AppError("not_found", "成员不存在", 404)
    if body.banned and subject.id == state.admin_subject_id:
        raise AppError("cannot_ban_admin", "请先完成管理员交接")
    if body.expires_at is not None and body.expires_at <= now():
        raise AppError("invalid_expiry", "新的注销时间必须晚于现在")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(subject, key, value)
    if body.banned:
        revoke(db, subject.id)
    db.commit()
    return {"ok": True}


@router.post("/students/{subject_id}/reset-password")
def reset_password(subject_id: uuid.UUID, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    subject = db.scalar(select(Subject).where(Subject.id == subject_id).with_for_update())
    if not subject:
        raise AppError("not_found", "成员不存在", 404)
    subject.password_hash = passwords.hash(subject.student_id)
    subject.must_change_password = True
    revoke(db, subject.id)
    db.commit()
    return {"ok": True}


class TransferInput(BaseModel):
    target_id: uuid.UUID
    password: str = Field(max_length=128)


@router.post("/transfer")
def transfer_admin(body: TransferInput, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    if state.admin_subject_id != actor.subject.id or not verify(actor.subject.password_hash, body.password):
        raise AppError("invalid_password", "管理员身份或密码不正确", 403)
    transfer(db, body.target_id)
    db.commit()
    return {"ok": True}


@router.post("/queue/{action}")
def queue_action(action: str, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    if action not in {"pause", "resume"}:
        raise AppError("invalid_action", "操作不存在", 404)
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    state.paused = action == "pause"
    db.commit()
    return {"paused": state.paused}


@router.get("/settings")
def get_settings(actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    state = db.get(SystemState, 1)
    return {
        "values": settings(state),
        "version": state.settings_version,
        "ranges": {key: {"min": minimum, "max": maximum} for key, (_, minimum, maximum) in SETTINGS.items()},
    }


class SettingsInput(BaseModel):
    version: int
    values: dict[str, int]


@router.patch("/settings")
def update_settings(body: SettingsInput, actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    if state.settings_version != body.version:
        raise AppError("settings_conflict", "配置已被修改，请刷新", 409)
    for key, value in body.values.items():
        if key not in SETTINGS or not SETTINGS[key][1] <= value <= SETTINGS[key][2]:
            raise AppError("invalid_setting", "配置项或数值超出范围")
    state.settings = {**state.settings, **body.values}
    state.settings_version += 1
    db.commit()
    return {"version": state.settings_version, "values": settings(state)}


def stats_query(start, end, student_id):
    query = select(
        Subject.student_id,
        func.count(History.id).label("task_count"),
        func.sum(History.total_pages).label("planned_pages"),
    ).join(History, History.subject_id == Subject.id)
    if start:
        query = query.where(History.created_at >= start)
    if end:
        query = query.where(History.created_at < end)
    if student_id:
        query = query.where(Subject.student_id == student_id)
    return query.group_by(Subject.student_id).order_by(Subject.student_id)


@router.get("/stats")
def stats(
    start: datetime | None = None,
    end: datetime | None = None,
    student_id: str | None = None,
    actor: Actor = Depends(admin_actor),
    db: Session = Depends(get_db),
):
    rows = db.execute(stats_query(start, end, student_id)).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.get("/stats.csv")
def stats_csv(
    start: datetime | None = None,
    end: datetime | None = None,
    student_id: str | None = None,
    actor: Actor = Depends(admin_actor),
    db: Session = Depends(get_db),
):
    from urllib.parse import quote

    rows = db.execute(stats_query(start, end, student_id)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["student_id", "task_count", "planned_pages"])
    for row in rows:
        identity = "'" + row[0] if row[0].startswith(("=", "+", "-", "@")) else row[0]
        writer.writerow([identity, row[1], row[2]])
    prefix = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", config().branding.platform_name).strip(". ")[:80] or "platform"
    )
    return Response(
        ("\ufeff" + output.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(prefix + "-stats.csv")},
    )


@router.get("/storage")
def storage(actor: Actor = Depends(admin_actor), db: Session = Depends(get_db)):
    import shutil

    from ..services.storage import root

    base = root()
    size = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
    db_size = db.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    return {
        "file_bytes": size,
        "database_bytes": db_size,
        "disk_free_bytes": shutil.disk_usage(base).free,
        "limit_bytes": settings(db.get(SystemState, 1))["storage_limit_gb"] * 1000000000,
    }
