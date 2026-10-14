import csv
import io

from sqlalchemy import select

from ..domain import validate_email, validate_identity, validate_phone
from ..errors import AppError
from ..models import Subject, SystemState, now
from ..security import revoke


def parse_import(data: bytes):
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames:
            aliases = {"email（选填）": "email", "phone（选填）": "phone"}
            reader.fieldnames = [aliases.get(name, name) for name in reader.fieldnames]
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise AppError("invalid_csv", "CSV 存在重复列")
        if not reader.fieldnames or "student_id" not in reader.fieldnames:
            raise AppError("invalid_csv", "CSV 缺少 student_id 列")
        if set(reader.fieldnames) - {"student_id", "email", "phone"}:
            raise AppError("invalid_csv", "CSV 仅允许 student_id、email、phone 列")
        rows, seen = [], set()
        for line, raw in enumerate(reader, 2):
            if len(rows) >= 10000:
                raise AppError("invalid_csv", "单次最多 10000 行")
            identity = (raw.get("student_id") or "").strip()
            email = raw.get("email") or ""
            phone = raw.get("phone") or ""
            error = None
            try:
                identity = validate_identity(identity)
                email = validate_email(email)
                phone = validate_phone(raw.get("phone") or "")
                if None in raw or len(raw.get("phone") or "") > 64:
                    raise ValueError("列数或联系方式长度错误")
            except ValueError as exc:
                error = str(exc)
            duplicate = identity in seen
            seen.add(identity)
            rows.append(
                {
                    "line": line,
                    "student_id": identity,
                    "email": email,
                    "phone": phone,
                    "status": "invalid" if error else "skipped" if duplicate else "new",
                    "reason": error or ("文件内重复" if duplicate else ""),
                }
            )
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise AppError("invalid_csv", "请使用 UTF-8 CSV 文件") from exc


def transfer(db, target_id):
    state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
    target = db.scalar(select(Subject).where(Subject.id == target_id).with_for_update())
    if not target or target.banned or target.expires_at <= now() or target.id == state.admin_subject_id:
        raise AppError("invalid_transfer", "接任成员必须存在、未封禁、未到期且不是当前管理员")
    old = state.admin_subject_id
    state.admin_subject_id = target.id
    revoke(db, old)
    revoke(db, target.id)
