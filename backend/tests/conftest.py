"""Shared fixtures.

The test database is rebuilt from nothing once per session by running the real migrations, so
every test run also proves `alembic upgrade head` works on an empty database. Each test then
runs inside a transaction that is rolled back, with the session in savepoint mode.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.jobs.migrate import run_migrations
from app.models.catalogue import Category, Product
from app.models.suppliers import Supplier
from app.models.tenancy import Tenant, User
from tests import factories

TEST_DB_NAME = "backroom_test"


def _with_database(url: str, name: str) -> str:
    return make_url(url).set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    url = explicit or _with_database(get_settings().database_url, TEST_DB_NAME)
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.exit(f"Refusing to run tests against database {name!r}: the name must end in _test")
    return url


def reset_database(url: str) -> None:
    """Create the database if missing, then empty its public schema."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()
    engine = create_engine(target, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        # Same default as a fresh database: every role can see the schema, not create in it.
        conn.execute(text("GRANT USAGE ON SCHEMA public TO PUBLIC"))
    engine.dispose()


@contextmanager
def scratch_database(base_url: str, name: str) -> Iterator[str]:
    """A throwaway empty database, dropped afterwards. For tests that run migrations."""
    assert name.endswith("_test")
    target = make_url(base_url).set(database=name)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield target.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    reset_database(test_database_url)
    run_migrations(test_database_url)
    eng = create_engine(test_database_url, pool_size=3, max_overflow=2)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test."""
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@contextmanager
def rejected(
    db: Session, exc: type[Exception] = IntegrityError, match: str | None = None
) -> Iterator[None]:
    """Expect the database to refuse the statements in the block.

    The block runs in a savepoint, so the surrounding test transaction stays usable.
    """
    try:
        with db.begin_nested():
            yield
            db.flush()
    except exc as caught:
        if match and not re.search(match, str(caught)):
            raise AssertionError(f"Error did not match {match!r}: {caught}") from caught
        return
    raise AssertionError(f"Expected the database to raise {exc.__name__}")


@dataclass
class TenantBundle:
    tenant: Tenant
    user: User
    category: Category
    product: Product
    supplier: Supplier
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class TwoTenants:
    a: TenantBundle
    b: TenantBundle


def _bundle(db: Session, settings: Settings, slug_hint: str) -> TenantBundle:
    tenant = factories.make_tenant(db, slug=f"{slug_hint}-{factories.short_id()}")
    user = factories.make_user(db, tenant)
    category = factories.make_category(db, tenant)
    return TenantBundle(
        tenant=tenant,
        user=user,
        category=category,
        product=factories.make_product(db, tenant, category=category),
        supplier=factories.make_supplier(db, tenant),
        headers=factories.auth_headers(settings, user),
    )


@pytest.fixture
def two_tenants(db: Session, test_settings: Settings) -> TwoTenants:
    """Two tenants, each with an owner, a category, a product and a supplier."""
    return TwoTenants(a=_bundle(db, test_settings, "alpha"), b=_bundle(db, test_settings, "bravo"))


@pytest.fixture
def test_settings(test_database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=test_database_url,
        cors_origins=["http://localhost:5173"],
        # Cheap password hashing keeps the suite fast. Production keeps the spec parameters.
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        # Rate limit tests switch this on for themselves.
        rate_limit_enabled=False,
        _env_file=None,  # type: ignore[call-arg]
    )
