"""Small helpers shared by the services: errors with a consistent voice, slugs, numbering."""

import hashlib
import re
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.schemas.common import ErrorDetail

SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def not_found(what: str, *, field: str | None = None) -> AppError:
    """404 with a message that names the kind of thing, never the id."""
    details = [ErrorDetail(field=field, issue="not found")] if field else None
    return AppError(ErrorCode.NOT_FOUND, f"We could not find that {what}.", details=details)


def invalid(field: str, issue: str, message: str | None = None) -> AppError:
    """422 for one field."""
    return AppError(
        ErrorCode.VALIDATION_ERROR, message, details=[ErrorDetail(field=field, issue=issue)]
    )


def conflict(message: str, *, field: str | None = None) -> AppError:
    details = [ErrorDetail(field=field, issue=message)] if field else None
    return AppError(ErrorCode.CONFLICT, message, details=details)


def slugify(value: str, *, fallback: str = "item", limit: int = 40) -> str:
    return SLUG_UNSAFE.sub("-", value.lower()).strip("-")[:limit].strip("-") or fallback


def escape_like(term: str) -> str:
    """Make `%`, `_` and the escape character literal inside a LIKE pattern."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def advisory_lock(session: Session, *parts: str | uuid.UUID) -> None:
    """Hold a transaction scoped lock named by `parts`. Serialises number generation and
    idempotent replays for one tenant without touching other tenants."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def next_number(
    session: Session,
    tenant_id: uuid.UUID,
    column: ColumnElement[Any],
    tenant_column: ColumnElement[Any],
    *,
    prefix: str,
    on: date,
    width: int,
) -> str:
    """The next document number such as `B2610-00042`, continuing whatever exists.

    Callers hold `advisory_lock` for the document kind first, so two requests never read the
    same last number.
    """
    stem = f"{prefix}{on:%y%m}-"
    last = session.execute(
        select(column)
        .where(tenant_column == tenant_id, column.like(f"{stem}%"))
        .order_by(column.desc())
        .limit(1)
    ).scalar_one_or_none()
    sequence = 1
    if last is not None:
        tail = str(last).removeprefix(stem)
        if tail.isdigit():
            sequence = int(tail) + 1
    return f"{stem}{sequence:0{width}d}"


def first_or_none[T](rows: Sequence[T]) -> T | None:
    return rows[0] if rows else None
