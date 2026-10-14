"""Single executable entry point; each role still runs as an independent process."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Printing platform")
    sub = parser.add_subparsers(dest="role", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    for role in ("conversion", "printing", "maintenance", "migrate", "check-config", "check-runtime"):
        sub.add_parser(role)
    transfer = sub.add_parser("transfer")
    transfer.add_argument("--student-id", required=True)
    args = parser.parse_args()
    if args.role == "serve":
        import uvicorn

        uvicorn.run("print_platform.main:app", host=args.host, port=args.port)
    elif args.role == "check-runtime":
        import importlib

        from print_platform.config import ROOT, config

        config()
        for name in ("print_platform.main", "print_platform.workers.conversion", "print_platform.workers.printing", "print_platform.workers.maintenance", "pypdfium2", "psycopg", "sqlalchemy.dialects.postgresql.psycopg", "win32print", "win32ui", "win32gui"):
            importlib.import_module(name)
        for path in ("frontend/dist/index.html", "frontend/public/brand/favicon.svg", "backend/migrations/001_initial.sql"):
            if not (ROOT / path).is_file():
                raise RuntimeError("Missing bundled runtime data: " + path)
        print("Runtime dependencies and assets OK")
    elif args.role in {"conversion", "printing", "maintenance"}:
        from print_platform.workers import conversion, maintenance, printing

        {"conversion": conversion, "printing": printing, "maintenance": maintenance}[args.role].main()
    else:
        from print_platform.cli import main as cli_main

        sys.argv = [sys.argv[0], args.role]
        if args.role == "transfer":
            sys.argv.extend(["--student-id", args.student_id])
        cli_main()


if __name__ == "__main__":
    main()
