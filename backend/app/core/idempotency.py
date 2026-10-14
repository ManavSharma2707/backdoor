"""Idempotent POSTs (`api-spec.md` section 1).

A client sends `Idempotency-Key`. The first request runs and its response is stored with a hash
of the request. The same key and the same body later returns the stored response (header
`Idempotent-Replay: true`) without running anything again. The same key with a different body
is a 422. Stored responses expire after `IDEMPOTENCY_TTL_HOURS`.

Everything happens in one transaction: the stored response commits together with the work it
describes, so a crash can never leave work done without its key, or a key without its work. A
per key advisory lock makes two simultaneous requests with one key run one after the other, and
the second then sees the first one's stored response.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.config import Settings
from app.core.db import advisory_lock, transaction
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.models.ops import IdempotencyKey as StoredKey
from app.schemas.common import ErrorDetail

KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
REPLAY_HEADER = "Idempotent-Replay"


def idempotency_key_header(
    key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="8 to 64 characters: letters, digits, dot, underscore, colon, hyphen",
        ),
    ] = None,
) -> str | None:
    if key is not None and not KEY_PATTERN.match(key):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The Idempotency-Key header must be 8 to 64 letters, digits or . _ : -",
            details=[ErrorDetail(field="Idempotency-Key", issue="has the wrong format")],
        )
    return key


IdempotencyKey = Annotated[str | None, Depends(idempotency_key_header)]


def _canonical(value: Any) -> Any:
    """JSON form used for hashing: numbers by value (`1` and `1.000` are the same quantity),
    instants in UTC, everything else as text."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def request_hash(body: BaseModel | dict[str, Any] | None) -> str:
    """Hash of the request body in a canonical form, so field order and number formatting do
    not change it."""
    payload = body.model_dump(mode="python") if isinstance(body, BaseModel) else (body or {})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_canonical)
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_idempotent(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    settings: Settings,
    key: str | None,
    scope: str,
    body: BaseModel | dict[str, Any] | None,
    response: Response,
    status_code: int,
    build: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run `build` once per (tenant, key, scope) and return its JSON result.

    `scope` names the operation and its target, for example `POST /sales` or
    `POST /sales/<id>/returns`, so one key can be reused on different operations.
    Without a key the work still runs in a transaction, just without replay protection.
    """
    response.status_code = status_code
    if key is None:
        with transaction(session):
            return build()

    digest = request_hash(body)
    with transaction(session):
        advisory_lock(session, tenant_id, "idempotency", scope, key)
        now = now_utc()
        stored = session.execute(
            select(StoredKey).where(
                StoredKey.tenant_id == tenant_id,
                StoredKey.key == key,
                StoredKey.endpoint == scope,
            )
        ).scalar_one_or_none()
        if stored is not None and stored.expires_at <= now:
            session.delete(stored)
            session.flush()
            stored = None
        if stored is not None:
            if stored.request_hash != digest:
                raise AppError(ErrorCode.IDEMPOTENCY_MISMATCH)
            response.status_code = stored.response_status
            response.headers[REPLAY_HEADER] = "true"
            return stored.response_body

        result = build()
        session.add(
            StoredKey(
                tenant_id=tenant_id,
                key=key,
                endpoint=scope,
                request_hash=digest,
                response_status=status_code,
                response_body=result,
                expires_at=now + timedelta(hours=settings.idempotency_ttl_hours),
            )
        )
        session.flush()
        return result


def prune_expired(session: Session) -> int:
    """Delete keys past their expiry. Called by the nightly cleanup in the Monday job."""
    result = session.execute(delete(StoredKey).where(StoredKey.expires_at <= now_utc()))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
