import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@lru_cache
def engine():
    url = os.environ.get("PLATFORM_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("请配置 PLATFORM_DATABASE_URL=postgresql+psycopg://...")
    return create_engine(
        url, pool_size=5, max_overflow=5, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )


def session():
    return Session(engine(), expire_on_commit=False)


def get_db():
    with session() as db:
        yield db
