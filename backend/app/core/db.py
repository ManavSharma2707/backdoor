"""Engine and session factory, sized for the Supabase session pooler.

The pool is deliberately small (`pool_size=5, max_overflow=2`): the free plan has few
connections and Render free has 512 MB. With a transaction pooler (port 6543) prepared
statements must be off, which `DATABASE_TRANSACTION_POOLER=true` does.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

POOL_RECYCLE_SECONDS = 1800


def make_engine(settings: Settings, **overrides: Any) -> Engine:
    connect_args: dict[str, Any] = {}
    if settings.database_transaction_pooler:
        connect_args["prepare_threshold"] = None
    options: dict[str, Any] = {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": POOL_RECYCLE_SECONDS,
        "connect_args": connect_args,
    }
    options.update(overrides)
    return create_engine(settings.database_url, **options)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings())


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards.

    Services own the transaction (`with session.begin():`), so nothing commits here.
    """
    with get_session_factory()() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction for scripts and jobs: commit on success, roll back on error."""
    with get_session_factory()() as session, session.begin():
        yield session


def dispose_engine() -> None:
    """Close pooled connections (used on shutdown and in tests)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
