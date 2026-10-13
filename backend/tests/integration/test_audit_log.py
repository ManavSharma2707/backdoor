"""The audit log is append only: UPDATE, DELETE and TRUNCATE are refused."""

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ops import AuditLog
from tests.conftest import rejected


def _log(db: Session, **overrides: Any) -> AuditLog:
    values: dict[str, Any] = {
        "tenant_id": uuid4(),
        "action": "auth.login.success",
        "request_id": "req-12345678",
    }
    entry = AuditLog(**{**values, **overrides})
    db.add(entry)
    db.flush()
    return entry


def test_rows_can_be_appended(db: Session) -> None:
    first, second = _log(db), _log(db, action="sale.create")
    assert second.id > first.id
    assert first.created_at is not None


def test_update_is_rejected(db: Session) -> None:
    entry = _log(db)
    with rejected(db, match="append only"):
        db.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"), {"id": entry.id}
        )


def test_update_through_the_orm_is_rejected(db: Session) -> None:
    entry = _log(db)
    with rejected(db, match="append only"):
        entry.action = "tampered"


def test_delete_is_rejected(db: Session) -> None:
    entry = _log(db)
    with rejected(db, match="append only"):
        db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": entry.id})


def test_truncate_is_rejected(db: Session) -> None:
    _log(db)
    with rejected(db, match="append only"):
        db.execute(text("TRUNCATE audit_logs"))


def test_the_row_survives_every_attempt(db: Session) -> None:
    entry = _log(db)
    for statement in (
        "UPDATE audit_logs SET action = 'x' WHERE id = :id",
        "DELETE FROM audit_logs WHERE id = :id",
    ):
        with rejected(db):
            db.execute(text(statement), {"id": entry.id})
    action = db.execute(
        text("SELECT action FROM audit_logs WHERE id = :id"), {"id": entry.id}
    ).scalar()
    assert action == "auth.login.success"
