import logging

from sqlalchemy import select

from ..adapters import adapter
from ..db import session
from ..domain import settings
from ..models import Batch, History, PrintTask, RenderPlan, Subject, SystemState, now
from ..services.storage import ensure_space, resolve
from .runtime import run

log = logging.getLogger(__name__)


def record_job(task_id, reference):
    with session() as db:
        task = db.scalar(select(PrintTask).where(PrintTask.id == task_id).with_for_update())
        if not task.job_ref:
            task.job_ref, task.submitted_at = reference, now()
        task.state, task.updated_at = "submitted", now()
        if not db.scalar(select(History).where(History.task_id == task.id)):
            plan, batch = db.get(RenderPlan, task.plan_id), db.get(Batch, task.batch_id)
            db.add(
                History(
                    task_id=task.id,
                    subject_id=batch.owner_id,
                    total_pages=len(plan.page_numbers) * task.copies,
                    created_at=task.submitted_at,
                )
            )
        db.commit()


def reconcile(printer):
    with session() as db:
        ids = list(
            db.scalars(
                select(PrintTask.id).where(
                    PrintTask.state.in_(["submitting", "submitted", "printing", "cancelling", "unknown"])
                )
            ).all()
        )
    for task_id in ids:
        with session() as db:
            task = db.scalar(select(PrintTask).where(PrintTask.id == task_id).with_for_update())
            if not task.job_ref:
                found = printer.find_job(task.marker)
                if found:
                    db.rollback()
                    record_job(task_id, found)
                    continue
                if task.state == "submitting":
                    task.state, task.updated_at = "unknown", now()
                    db.commit()
                continue
            status = printer.query_job(task.job_ref)
            if not status["present"]:
                task.state = "cancelled" if task.cancel_confirmed else "queue_ended"
            elif task.cancel_requested and printer.capabilities()["cancel_supported"]:
                if not task.cancel_confirmed and printer.cancel_job(task.job_ref):
                    task.cancel_confirmed = True
                task.state = "cancelling" if task.cancel_confirmed else "printing"
            else:
                task.state = "printing"
            task.updated_at = now()
            db.commit()


def tick(guard):
    printer = adapter()
    try:
        status = printer.device_status()
    except Exception:
        log.exception("Device status unavailable")
        status = {"available": False, "blocked": True, "message": "设备状态查询不可用", "toner": "unknown"}
    with session() as db:
        state = db.get(SystemState, 1)
        state.device, state.device_checked_at = status, now()
        db.commit()
    if not status["available"]:
        return
    reconcile(printer)  # A query failure aborts the tick; it cannot release later tasks.
    if status["blocked"]:
        return
    with session() as db:
        state = db.get(SystemState, 1)
        if state.paused or db.scalar(
            select(PrintTask.id).where(PrintTask.state.in_(["submitted", "printing", "cancelling"])).limit(1)
        ):
            return
        task = db.scalar(
            select(PrintTask)
            .join(Batch, Batch.id == PrintTask.batch_id)
            .where(PrintTask.state == "queued")
            .order_by(Batch.sequence, PrintTask.position)
            .with_for_update(of=PrintTask, skip_locked=True)
            .limit(1)
        )
        if not task:
            return
        subject = db.get(Subject, db.get(Batch, task.batch_id).owner_id)
        if subject.expires_at <= now() and subject.id != state.admin_subject_id:
            task.state, task.updated_at = "cancelled", now()
            db.commit()
            return
        ensure_space(settings(state))
        plan = db.get(RenderPlan, task.plan_id)
        if plan.geometry != printer.capabilities(plan.orientation)["geometry"]:
            task.state, task.diagnostic = "failed", "Device geometry changed; create a new preview"
            db.commit()
            return
        guard()
        task.state, task.marker, task.updated_at = "submitting", "platform-task-" + str(task.id), now()
        db.commit()
        task_id, marker, copies, orientation, path = (
            task.id,
            task.marker,
            task.copies,
            plan.orientation,
            resolve(plan.storage_key),
        )
    try:
        guard()
        printer.submit(path, copies, orientation, marker, lambda reference: record_job(task_id, reference))
    except Exception:
        log.exception("Submission failed: %s", task_id)
        with session() as db:
            task = db.get(PrintTask, task_id)
            # Generic external failures are conservatively unknown; never blindly retry.
            task.state, task.diagnostic, task.updated_at = (
                "unknown",
                "Submission interrupted; reconciliation required",
                now(),
            )
            db.commit()


def main():
    run(60112, tick)


if __name__ == "__main__":
    main()
