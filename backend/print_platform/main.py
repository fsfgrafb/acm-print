import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import admin, files, identity, printing
from .config import ROOT, config
from .db import session
from .errors import AppError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    config()  # Fail early for invalid deployment configuration, never create schema at startup.
    yield


app = FastAPI(title="Printing platform API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin != config().server.public_origin:
            return error_response(request, "origin_rejected", "请求来源不正确", 403)
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > 1025 * 1048576:
                    return error_response(request, "request_too_large", "请求体过大", 413)
            except ValueError:
                return error_response(request, "invalid_request", "请求长度不正确", 400)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


def error_response(request, code, message, status):
    return JSONResponse(
        {"code": code, "message": message, "request_id": getattr(request.state, "request_id", "")},
        status_code=status,
    )


@app.exception_handler(AppError)
async def application_error(request, exc):
    return error_response(request, exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error_response(request, "invalid_request", "请求字段格式不正确", 422)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    log.exception("Database operation failed; request=%s", getattr(request.state, "request_id", ""))
    return error_response(request, "database_unavailable", "数据库暂不可用，请稍后重试", 503)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    log.exception("Unexpected failure; request=%s", getattr(request.state, "request_id", ""))
    return error_response(request, "internal_error", "操作暂时无法完成，请稍后重试", 500)


@app.get("/api/public/branding")
def branding():
    return JSONResponse(config().branding.model_dump(), headers={"Cache-Control": "no-store"})


@app.get("/api/health/live")
def live():
    return {"status": "alive"}


@app.get("/api/health/ready")
def ready():
    with session() as db:
        db.execute(text("SELECT id FROM system_state WHERE id=1")).scalar_one()
    return {"status": "ready"}


for router in (identity.router, files.router, printing.router, admin.router):
    app.include_router(router, prefix="/api")

dist = ROOT / "frontend/dist"
app.mount("/brand", StaticFiles(directory=ROOT / "frontend/public/brand"), name="brand")
if (dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def favicon():
    icon = ROOT / "frontend/public" / config().branding.icon_url.lstrip("/")
    if not icon.is_file():
        raise AppError("not_found", "图标资源不存在", 404)
    return FileResponse(icon, headers={"Cache-Control": "no-cache"})


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/") or not (dist / "index.html").exists():
        raise AppError("not_found", "资源不存在；请先构建前端", 404)
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
