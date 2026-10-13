"""Migrations run from nothing, back to nothing, and up again, with no model drift."""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.jobs import migrate
from app.models import Base
from tests.conftest import scratch_database

SUPABASE_ROLES = ("anon", "authenticated")


@pytest.fixture
def empty_database(test_database_url: str) -> Iterator[str]:
    with scratch_database(test_database_url, "backroom_migrations_test") as url:
        yield url


def _scalar_set(url: str, sql: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = {str(row[0]) for row in conn.execute(text(sql))}
    engine.dispose()
    return rows


def _public_tables(url: str) -> set[str]:
    return _scalar_set(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")


def test_upgrade_downgrade_upgrade(empty_database: str) -> None:
    expected = set(Base.metadata.tables) | {"alembic_version"}

    migrate.upgrade(empty_database)
    assert _public_tables(empty_database) == expected

    migrate.downgrade(empty_database)
    assert _public_tables(empty_database) <= {"alembic_version"}
    assert not _scalar_set(
        empty_database,
        "SELECT proname FROM pg_proc WHERE proname IN ('set_updated_at', 'audit_logs_immutable')",
    )
    assert not _scalar_set(
        empty_database, "SELECT viewname FROM pg_views WHERE schemaname = 'public'"
    )

    migrate.upgrade(empty_database)
    assert _public_tables(empty_database) == expected


def test_models_and_migrations_agree(empty_database: str) -> None:
    migrate.upgrade(empty_database)
    # Raises CommandError when autogenerate would produce any operation.
    command.check(migrate.alembic_config(empty_database))


def test_every_table_has_row_level_security(empty_database: str) -> None:
    migrate.upgrade(empty_database)
    unprotected = _scalar_set(
        empty_database,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
        "AND relkind = 'r' AND NOT relrowsecurity",
    )
    assert unprotected == set()


def test_run_migrations_is_repeatable_and_loads_reference_data(empty_database: str) -> None:
    migrate.run_migrations(empty_database)
    migrate.run_migrations(empty_database)
    assert _scalar_set(empty_database, "SELECT code FROM tax_rates") == {
        "GST0",
        "GST5",
        "GST18",
        "GST40",
    }
    assert _scalar_set(empty_database, "SELECT count(*) FROM calendar_events") == {"28"}


def test_supabase_api_roles_lose_access(empty_database: str) -> None:
    """Simulate Supabase, where new tables are granted to anon and authenticated by default."""
    engine = create_engine(empty_database, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for role in SUPABASE_ROLES:
            conn.execute(
                text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                    f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
                )
            )
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            conn.execute(
                text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {role}")
            )
    migrate.upgrade(empty_database)
    with engine.connect() as conn:
        for role in SUPABASE_ROLES:
            for table in ("tenants", "products", "sale_lines", "v_product_stock"):
                allowed = conn.execute(
                    text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                    {"role": role, "table": f"public.{table}"},
                ).scalar()
                assert allowed is False, f"{role} can still read {table}"
        # PUBLIC keeps USAGE on the schema by default, so check the explicit grants instead.
        acl = conn.execute(
            text("SELECT coalesce(nspacl::text, '') FROM pg_namespace WHERE nspname = 'public'")
        ).scalar()
        for role in SUPABASE_ROLES:
            assert f"{role}=" not in str(acl)
    engine.dispose()
