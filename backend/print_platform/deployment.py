"""Read-only deployment inspection and PostgreSQL backup for the release updater."""

import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from .config import config
from .db import engine


def update_check(install_root: str, dump_to: str | None = None, pg_bin: str | None = None):
    root = Path(install_root).resolve(strict=True)
    storage = Path(config().storage.root)
    storage = storage.resolve() if storage.is_absolute() else (root / storage).resolve()
    with engine().connect() as connection:
        count = connection.execute(text(
            "SELECT count(*) FROM print_tasks WHERE state IN "
            "('submitting', 'submitted', 'printing', 'cancelling')"
        )).scalar_one()
    if count:
        raise RuntimeError(f"还有 {count} 个任务正在提交、打印或取消，请等待任务结束后更新。")
    if dump_to:
        destination = Path(dump_to)
        if destination.exists():
            raise FileExistsError("数据库备份文件已存在。")
        url = make_url(os.environ["PLATFORM_DATABASE_URL"])
        from psycopg.conninfo import make_conninfo

        params = url.translate_connect_args(username="user", database="dbname")
        params.update(url.query)
        password = params.pop("password", "")
        environment = os.environ.copy()
        environment["PGPASSWORD"] = password
        environment["PGCONNECT_TIMEOUT"] = "10"
        program = str(Path(pg_bin) / "pg_dump.exe") if pg_bin else "pg_dump"
        result = subprocess.run([
            program, "--no-password", "--format=custom", "--file", str(destination),
            "--dbname", make_conninfo(**params),
        ], env=environment, capture_output=True, text=True, check=False)
        if result.returncode:
            # Do not echo connection details, credentials, or arbitrary server diagnostics.
            raise RuntimeError("pg_dump 备份失败，请检查 PostgreSQL 工具版本、连接权限和磁盘空间。")
        if not destination.is_file() or not destination.stat().st_size:
            raise RuntimeError("数据库备份为空。")
    print(json.dumps({"storage_path": str(storage)}, ensure_ascii=True))
