from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import config
from ..db import get_db
from ..domain import four_years, settings, validate_email, validate_identity, validate_phone
from ..errors import AppError
from ..models import Subject, SystemState, now
from ..security import Actor, actor_json, current_actor, issue_session, passwords, revoke, verify

router = APIRouter()


class Credentials(BaseModel):
    student_id: str = Field(max_length=64)
    password: str = Field(max_length=128)


class Setup(BaseModel):
    student_id: str = Field(max_length=64)


class PasswordChange(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(max_length=128)


class Profile(BaseModel):
    email: str = Field(max_length=254)
    phone: str = Field(max_length=64)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        return validate_email(value)

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value):
        return validate_phone(value)


@router.get("/setup/status")
def setup_status(db: Session = Depends(get_db)):
    state = db.get(SystemState, 1)
    return {"initialized": state.initialized}


@router.post("/setup")
def setup(body: Setup, db: Session = Depends(get_db)):
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    if state.initialized:
        raise AppError("already_initialized", "系统已初始化", 409)
    try:
        identity = validate_identity(body.student_id)
    except ValueError as error:
        raise AppError("invalid_identity", config().branding.identity_label + str(error)) from error
    created = now()
    subject = Subject(
        student_id=identity,
        password_hash=passwords.hash(identity),
        created_at=created,
        expires_at=four_years(created),
    )
    db.add(subject)
    db.flush()
    state.admin_subject_id, state.initialized = subject.id, True
    db.commit()
    return {"initialized": True}


@router.post("/auth/login")
def login(body: Credentials, response: Response, request: Request, db: Session = Depends(get_db)):
    # DB advisory transaction lock and a short-lived attempt bucket coordinate API instances.
    key = (request.client.host if request.client else "local") + ":" + body.student_id.strip()
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "login:" + key})
    attempts = db.execute(
        text("""
        INSERT INTO login_throttle (bucket, started_at, attempts) VALUES (:key, now(), 1)
        ON CONFLICT (bucket) DO UPDATE SET
          attempts = CASE WHEN login_throttle.started_at < now() - interval '5 minutes'
                     THEN 1 ELSE login_throttle.attempts + 1 END,
          started_at = CASE WHEN login_throttle.started_at < now() - interval '5 minutes'
                       THEN now() ELSE login_throttle.started_at END RETURNING attempts
    """),
        {"key": key},
    ).scalar_one()
    db.commit()
    if attempts > 20:
        raise AppError("login_throttled", "尝试过于频繁，请稍后再试", 429)
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    subject = db.scalar(
        select(Subject).where(Subject.student_id == body.student_id.strip()).with_for_update()
    )
    if not subject or not verify(subject.password_hash, body.password):
        raise AppError("invalid_credentials", config().branding.identity_label + "或密码不正确", 401)
    admin = state.admin_subject_id == subject.id
    if subject.banned or (subject.expires_at <= now() and not admin):
        raise AppError("account_unavailable", "账号已封禁或到期", 403)
    token, csrf = issue_session(db, subject.id, settings(state)["session_days"])
    db.commit()
    response.set_cookie(
        "platform_session",
        token,
        httponly=True,
        samesite="lax",
        secure=config().server.secure_cookie,
        max_age=settings(state)["session_days"] * 86400,
    )
    return actor_json(Actor(subject, admin, csrf))


@router.get("/auth/me")
def me(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    result = actor_json(actor)
    admin = db.get(Subject, db.get(SystemState, 1).admin_subject_id)
    result["admin_contact"] = {"email": admin.email, "phone": admin.phone}
    return result


@router.post("/auth/logout")
def logout(response: Response, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    # Only this session is removed when logging out.
    from sqlalchemy import delete

    from ..models import LoginSession

    db.execute(
        delete(LoginSession).where(
            LoginSession.subject_id == actor.subject.id, LoginSession.csrf_token == actor.csrf
        )
    )
    db.commit()
    response.delete_cookie("platform_session")
    return {"ok": True}


@router.post("/auth/change-password")
def change_password(
    body: PasswordChange,
    response: Response,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    subject = db.scalar(select(Subject).where(Subject.id == actor.subject.id).with_for_update())
    if not subject.must_change_password and (
        body.current_password is None or not verify(subject.password_hash, body.current_password)
    ):
        raise AppError("invalid_password", "当前密码不正确", 403)
    if not settings(db.get(SystemState, 1))["min_password_length"] <= len(body.new_password) <= 128:
        raise AppError("invalid_password_length", "密码长度不符合系统要求")
    subject.password_hash = passwords.hash(body.new_password)
    subject.must_change_password = False
    revoke(db, subject.id)
    token, csrf = issue_session(db, subject.id, settings(db.get(SystemState, 1))["session_days"])
    db.commit()
    response.set_cookie(
        "platform_session",
        token,
        httponly=True,
        samesite="lax",
        secure=config().server.secure_cookie,
        max_age=86400 * settings(db.get(SystemState, 1))["session_days"],
    )
    return actor_json(Actor(subject, actor.admin, csrf))


@router.patch("/profile")
def profile(body: Profile, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    actor.subject.email, actor.subject.phone = body.email, body.phone
    db.commit()
    return actor_json(actor)
