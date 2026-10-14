import hashlib
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select, text

from ..config import config
from ..errors import AppError
from ..models import Blob


def root():
    path = config().storage_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(key: str) -> Path:
    base = root()
    path = (base / key).resolve()
    if not path.is_relative_to(base):
        raise RuntimeError("存储键越界")
    return path


def temp_path(suffix=""):
    path = resolve("tmp/" + uuid.uuid4().hex + suffix)
    path.parent.mkdir(exist_ok=True)
    return path


def ensure_space(settings, extra=0):
    base = root()
    file_bytes = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
    from ..db import session

    with session() as db:
        database_bytes = db.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    if file_bytes + database_bytes + extra > settings["storage_limit_gb"] * 1000000000:
        raise AppError("storage_full", "存储额度不足，请联系管理员清理", 507)
    if shutil.disk_usage(base).free < extra + 256 * 1024 * 1024:
        raise AppError("disk_full", "磁盘剩余空间不足", 507)


def store_blob(db, path: Path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    # The content lock covers both the DB row and atomic file placement.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "blob:" + digest})
    existing = db.scalar(select(Blob).where(Blob.sha256 == digest))
    if existing:
        path.unlink(missing_ok=True)
        return existing
    key = f"blobs/{digest[:2]}/{digest}"
    target = resolve(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size
    os.replace(path, target)
    blob = Blob(sha256=digest, storage_key=key, byte_size=size)
    db.add(blob)
    db.flush()
    return blob
