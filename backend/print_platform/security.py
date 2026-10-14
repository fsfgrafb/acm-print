import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AppError
from .models import LoginSession, Subject, SystemState, now

passwords = PasswordHasher()


def verify(encoded, password):
    try:
        return passwords.verify(encoded, password)
    except VerificationError:
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Actor:
    subject: Subject
    admin: bool
    csrf: str


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    token = request.cookies.get("platform_session", "")
    login = db.get(LoginSession, token_hash(token)) if token else None
    if not login or login.expires_at <= now():
        raise AppError("unauthenticated", "请先登录", 401)
    subject = db.get(Subject, login.subject_id)
    state = db.get(SystemState, 1)
    admin = state.admin_subject_id == subject.id
    if subject.banned or (subject.expires_at <= now() and not admin):
        raise AppError("account_unavailable", "账号已封禁或到期", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), login.csrf_token):
            raise AppError("csrf_rejected", "请求凭证失效，请刷新页面", 403)
    if subject.must_change_password and request.url.path not in {
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/logout",
    }:
        raise AppError("password_change_required", "请先确认新密码", 403)
    return Actor(subject, admin, login.csrf_token)


def admin_actor(actor: Actor = Depends(current_actor)):
    if not actor.admin:
        raise AppError("forbidden", "需要管理员权限", 403)
    return actor


def revoke(db, subject_id):
    db.execute(delete(LoginSession).where(LoginSession.subject_id == subject_id))


def issue_session(db, subject_id: uuid.UUID, days: int):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=token_hash(token),
            subject_id=subject_id,
            csrf_token=csrf,
            expires_at=now() + timedelta(days=days),
        )
    )
    return token, csrf


def actor_json(actor):
    subject = actor.subject
    return {
        "id": str(subject.id),
        "student_id": subject.student_id,
        "admin": actor.admin,
        "must_change_password": subject.must_change_password,
        "email": subject.email,
        "phone": subject.phone,
        "expires_at": subject.expires_at.isoformat(),
        "created_at": subject.created_at.isoformat(),
        "csrf_token": actor.csrf,
    }
