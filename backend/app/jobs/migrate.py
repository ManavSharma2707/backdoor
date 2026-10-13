"""Run Alembic programmatically, under an advisory lock, then refresh reference data."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.jobs.reference_data import upsert_reference_data

log = get_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Any constant works as long as every instance uses the same one.
MIGRATION_LOCK_KEY = 726_001_001


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["configure_logger"] = False
    if database_url:
        config.attributes["database_url"] = database_url
    return config


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)


def run_migrations(database_url: str | None = None) -> None:
    """`alembic upgrade head` under `pg_advisory_lock`, then the reference data upsert.

    The lock lets several containers start at once (a deploy with two instances) without
    racing each other.
    """
    url = database_url or get_settings().database_url
    lock_engine = create_engine(url, isolation_level="AUTOCOMMIT", pool_size=1, max_overflow=0)
    with lock_engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        try:
            log.info("migrate.start")
            upgrade(url)
            seed_reference_data(url)
            log.info("migrate.done")
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
    lock_engine.dispose()


def seed_reference_data(database_url: str) -> None:
    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    with Session(engine) as session, session.begin():
        upsert_reference_data(session)
    engine.dispose()
