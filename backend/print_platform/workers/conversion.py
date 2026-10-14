import logging
import os
import time

from sqlalchemy import select

from ..db import session
from ..domain import settings
from ..errors import AppError
from ..models import Blob, Document, RenderPlan, SystemState
from ..services.documents import make_plan, normalize, plan_storage_key
from ..services.storage import resolve, store_blob
from .runtime import run

log = logging.getLogger(__name__)


def tick(guard):
    with session() as db:
        limits = settings(db.get(SystemState, 1))
        document = db.scalar(
            select(Document).where(Document.status == "processing").order_by(Document.created_at).limit(1)
        )
        if document:
            started = time.perf_counter()
            blob = db.get(Blob, document.original_blob_id)
            try:
                guard()
                output, count, version = normalize(resolve(blob.storage_key), document.source_ext, limits)
                normalized = blob if output == resolve(blob.storage_key) else store_blob(db, output)
                document.pdf_blob_id, document.page_count = normalized.id, count
                document.converter_version, document.status = version, "ready"
            except Exception as error:
                log.exception("Document preparation failed: %s", document.id)
                document.status = "failed"
                document.error_code = error.code if isinstance(error, AppError) else "conversion_failed"
            db.commit()
            log.info("Document %s prepared in %.3fs", document.id, time.perf_counter() - started)
            return True
        plan = db.scalar(
            select(RenderPlan)
            .where(RenderPlan.status == "processing")
            .order_by(RenderPlan.created_at)
            .limit(1)
        )
        if plan:
            started = time.perf_counter()
            try:
                guard()
                document = db.get(Document, plan.document_id)
                blob = db.get(Blob, document.pdf_blob_id)
                key = plan_storage_key(blob.sha256, plan.page_numbers, plan.geometry, plan.scaling)
                target = resolve(key)
                if not target.exists():
                    output = make_plan(
                        resolve(blob.storage_key), plan.page_numbers, plan.geometry, plan.scaling, limits
                    )
                    target.parent.mkdir(exist_ok=True)
                    os.replace(output, target)
                plan.storage_key, plan.status = key, "ready"
            except Exception as error:
                log.exception("Render plan failed: %s", plan.id)
                plan.status = "failed"
                plan.error_code = error.code if isinstance(error, AppError) else "render_failed"
            db.commit()
            log.info("Plan %s completed in %.3fs", plan.id, time.perf_counter() - started)
            return True


def main():
    run(60111, tick, idle_poll_cap=0.5)


if __name__ == "__main__":
    main()
