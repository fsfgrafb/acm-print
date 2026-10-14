import argparse
import hashlib
import logging

from sqlalchemy import select, text

from .config import ROOT, config
from .db import engine, session
from .errors import AppError
from .models import Subject
from .services.identity import transfer


def migrate():
    # Immutable SQL files with checksums; schema changes are explicit, never API startup side effects.
    with engine().begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(60100)"))
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, checksum text NOT NULL)"
        )
        for path in sorted((ROOT / "backend/migrations").glob("*.sql")):
            script = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(script.encode()).hexdigest()
            old = connection.execute(
                text("SELECT checksum FROM schema_migrations WHERE version=:version"), {"version": path.name}
            ).scalar_one_or_none()
            if old and old != checksum:
                raise RuntimeError("已应用迁移文件被修改：" + path.name)
            if not old:
                connection.exec_driver_sql(script)
                connection.execute(
                    text("INSERT INTO schema_migrations(version, checksum) VALUES(:version,:checksum)"),
                    {"version": path.name, "checksum": checksum},
                )
                print("Applied " + path.name)


def main():
    parser = argparse.ArgumentParser(description="打印平台本地部署工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("check-config")
    command = sub.add_parser("transfer")
    command.add_argument("--student-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        if args.command == "check-config":
            config()
            print("Configuration OK")
        elif args.command == "migrate":
            migrate()
        else:
            with session() as db:
                subject = db.scalar(select(Subject).where(Subject.student_id == args.student_id))
                if not subject:
                    raise AppError("not_found", "接任成员不存在")
                transfer(db, subject.id)
                db.commit()
                print("Administrator transferred; affected sessions revoked")
    except (AppError, ValueError, FileNotFoundError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
