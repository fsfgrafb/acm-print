import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Subject(Entity, Base):
    __tablename__ = "subjects"
    student_id: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SystemState(Base):
    __tablename__ = "system_state"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subjects.id"))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
    device: Mapped[dict] = mapped_column(JSONB, default=dict)
    device_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submit_visit_count: Mapped[int] = mapped_column(BigInteger, default=0)


class SubmitVisit(Entity, Base):
    __tablename__ = "submit_page_visits"


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Blob(Entity, Base):
    __tablename__ = "blobs"
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)


class Document(Entity, Base):
    __tablename__ = "documents"
    original_blob_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blobs.id"))
    pdf_blob_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("blobs.id"))
    source_ext: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    converter_version: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(64))


class Grant(Entity, Base):
    __tablename__ = "document_grants"
    __table_args__ = (UniqueConstraint("subject_id", "document_id"),)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))


class RenderPlan(Entity, Base):
    __tablename__ = "render_plans"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    page_numbers: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    orientation: Mapped[str] = mapped_column(String(20))
    scaling: Mapped[str] = mapped_column(String(20))
    geometry: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))


class Batch(Entity, Base):
    __tablename__ = "batches"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(
        BigInteger, unique=True, server_default=text("nextval('batch_sequence')")
    )


class Idempotency(Base):
    __tablename__ = "idempotency_entries"
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrintTask(Entity, Base):
    __tablename__ = "print_tasks"
    __table_args__ = (
        UniqueConstraint("batch_id", "position"),
        CheckConstraint("copies > 0"),
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("render_plans.id"))
    copies: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("print_tasks.id", ondelete="SET NULL")
    )
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    marker: Mapped[str | None] = mapped_column(String(100), unique=True)
    job_ref: Mapped[dict | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class History(Entity, Base):
    __tablename__ = "print_history"
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("print_tasks.id", ondelete="CASCADE"), unique=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    total_pages: Mapped[int] = mapped_column(Integer)


class ImportCommit(Base):
    __tablename__ = "import_commits"
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
