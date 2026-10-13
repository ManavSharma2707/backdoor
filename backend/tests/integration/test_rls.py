"""Row level security is on everywhere and there are no policies, so other roles see nothing."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from tests import factories
from tests.conftest import rejected

PROBE = "rls_probe"


@pytest.fixture
def probe_role(db: Session) -> str:
    """A role with no privileges. Creation is transactional, so the rollback removes it."""
    db.execute(text(f"CREATE ROLE {PROBE} NOLOGIN"))
    return PROBE


def test_every_public_table_has_rls_enabled(db: Session) -> None:
    unprotected = (
        db.execute(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                "AND relkind = 'r' AND NOT relrowsecurity"
            )
        )
        .scalars()
        .all()
    )
    assert unprotected == []


def test_there_are_no_policies(db: Session) -> None:
    policies = db.execute(text("SELECT count(*) FROM pg_policies")).scalar()
    assert policies == 0


def test_role_without_grants_is_denied(db: Session, probe_role: str) -> None:
    factories.make_tenant(db)
    with rejected(db, exc=ProgrammingError, match="permission denied"):
        db.execute(text(f"SET LOCAL ROLE {probe_role}"))
        db.execute(text("SELECT * FROM tenants"))


def test_role_with_read_grant_still_sees_zero_rows(db: Session, probe_role: str) -> None:
    """The Supabase Data API case: even a granted role gets nothing without a policy."""
    factories.make_tenant(db)
    factories.make_tenant(db)
    visible_to_owner = db.execute(text("SELECT count(*) FROM tenants")).scalar()
    assert visible_to_owner is not None
    assert visible_to_owner >= 2

    db.execute(text(f"GRANT SELECT ON tenants, products, sales TO {probe_role}"))
    db.execute(text(f"SET LOCAL ROLE {probe_role}"))
    try:
        for table in ("tenants", "products", "sales"):
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
    finally:
        db.execute(text("RESET ROLE"))


def test_role_cannot_write_even_with_a_grant(db: Session, probe_role: str) -> None:
    tenant = factories.make_tenant(db)
    db.execute(text(f"GRANT INSERT, UPDATE, DELETE, SELECT ON tenants TO {probe_role}"))
    db.execute(text(f"SET LOCAL ROLE {probe_role}"))
    try:
        updated = db.execute(
            text("UPDATE tenants SET name = 'hijacked' WHERE id = :id"), {"id": tenant.id}
        ).rowcount
        deleted = db.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant.id}).rowcount
        assert (updated, deleted) == (0, 0)
        with rejected(db, exc=Exception, match="row-level security"):
            db.execute(
                text("INSERT INTO tenants (slug, name, business_type) VALUES ('x', 'x', 'fmcg')")
            )
    finally:
        db.execute(text("RESET ROLE"))
    db.refresh(tenant)
    assert tenant.name == "Test Traders"
