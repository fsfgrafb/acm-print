"""Conservative maintenance. Automatic destructive history cleanup is not yet enabled."""

from sqlalchemy import delete, select, text

from ..db import session
from ..models import Batch, LoginSession, PrintTask, Subject, SystemState, now
from .runtime import run


def tick(guard):
    with session() as db:
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
        db.execute(text("DELETE FROM login_throttle WHERE started_at < now() - interval '1 day'"))
        state = db.get(SystemState, 1)
        expired = list(
            db.scalars(
                select(Subject.id).where(Subject.expires_at <= now(), Subject.id != state.admin_subject_id)
            ).all()
        )
        for subject_id in expired:
            db.execute(delete(LoginSession).where(LoginSession.subject_id == subject_id))
            batches = select(Batch.id).where(Batch.owner_id == subject_id)
            tasks = db.scalars(
                select(PrintTask)
                .where(PrintTask.batch_id.in_(batches), PrintTask.state == "queued")
                .with_for_update()
            ).all()
            for task in tasks:
                task.state, task.updated_at = "cancelled", now()
        db.commit()


def main():
    run(60113, tick)


if __name__ == "__main__":
    main()
