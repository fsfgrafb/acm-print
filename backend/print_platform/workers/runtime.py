import logging
import time
from contextlib import contextmanager

from sqlalchemy import text

from ..config import config
from ..db import engine, session
from ..domain import settings
from ..models import SystemState

log = logging.getLogger(__name__)


@contextmanager
def exclusive_worker(key):
    # Keep the coordinating session alive for the entire process lifetime.
    with engine().connect() as connection:
        if not connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one():
            raise RuntimeError("同类 worker 已运行")
        connection.commit()
        try:
            yield connection
        finally:
            if not connection.invalidated:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()


def heartbeat(connection):
    connection.execute(text("SELECT 1"))
    connection.commit()


def run(key, tick, *, idle_poll_cap=None):
    config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with exclusive_worker(key) as connection:
        while True:
            # A lost coordination connection exits the loop before another external action.
            heartbeat(connection)
            try:
                worked = tick(lambda: heartbeat(connection))
            except Exception:
                log.exception("Worker tick failed")
                worked = False
            if worked:
                continue
            with session() as db:
                delay = settings(db.get(SystemState, 1))["poll_seconds"]
            if idle_poll_cap is not None:
                delay = min(delay, idle_poll_cap)
            time.sleep(delay)
