"""Audit log writer (`security.md` section 6). Rows are append only, enforced by a trigger.

An event is recorded in the same transaction as the change it describes, so a rolled back
change leaves no audit row. Events that must survive a refusal (failed logins) are recorded and
committed by the caller before it raises.
"""

import hashlib
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.errors import request_id_of
from app.core.logging import REDACTED, is_sensitive_key
from app.models.ops import AuditLog

MAX_TEXT_LENGTH = 300
MAX_USER_AGENT_LENGTH = 300


class AuditAction(StrEnum):
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOCKOUT = "auth.lockout"
    LOGOUT = "auth.logout"
    LOGOUT_ALL = "auth.logout_all"
    REFRESH_REUSE = "auth.refresh_reuse"
    PASSWORD_CHANGE = "auth.password_change"  # noqa: S105
    REGISTER = "auth.register"
    SETTINGS_UPDATE = "settings.update"
    PRODUCT_CREATE = "product.create"
    PRODUCT_UPDATE = "product.update"
    PRODUCT_PRICE_CHANGE = "product.price_change"
    PRODUCT_DEACTIVATE = "product.deactivate"
    PRODUCT_ACTIVATE = "product.activate"
    CATEGORY_CREATE = "category.create"
    CATEGORY_UPDATE = "category.update"
    SUPPLIER_CREATE = "supplier.create"
    SUPPLIER_UPDATE = "supplier.update"
    TERMS_UPDATE = "terms.update"
    SALE_CREATE = "sale.create"
    SALE_VOID = "sale.void"
    RETURN_CREATE = "return.create"
    PO_CREATE = "po.create"
    PO_UPDATE = "po.update"
    PO_SEND = "po.send"
    PO_CANCEL = "po.cancel"
    PO_CLOSE = "po.close"
    RECEIPT_POST = "receipt.post"
    ADJUSTMENT_CREATE = "adjustment.create"
    SUPPLIER_RETURN = "supplier.return"
    COUNT_POST = "count.post"
    BATCH_WRITE_OFF = "batch.write_off"
    STOCKOUT_RECORD = "stockout.record"
    RECONCILE_RUN = "inventory.reconcile"
    PASSWORD_RESET = "auth.password_reset"  # noqa: S105
    REPORT_GENERATE = "report.generate"
    REPORT_EXPORT = "report.export"
    REPORT_NOTE = "report.note"
    DECISION_APPROVE = "decision.approve"
    DECISION_EDIT = "decision.edit"
    DECISION_REJECT = "decision.reject"
    REPORT_PO_CREATE = "report.po_create"
    DQ_RUN = "dq.run"


@dataclass(frozen=True)
class RequestMeta:
    """Where a request came from. Stored on audit rows and refresh tokens."""

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def clean_ip(value: str | None) -> str | None:
    """Only a real IP address can go into the `inet` column."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def meta_from_request(request: Request) -> RequestMeta:
    client = request.client
    agent = request.headers.get("user-agent")
    return RequestMeta(
        ip=clean_ip(client.host if client else None),
        user_agent=agent[:MAX_USER_AGENT_LENGTH] if agent else None,
        request_id=request_id_of(request),
    )


def email_fingerprint(email: str) -> str:
    """Stable short hash of an email, so failed logins can be grouped without storing it."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def json_safe(value: Any) -> Any:
    """Make `value` storable as JSON: money as strings, sensitive keys redacted, text clipped."""
    if isinstance(value, dict):
        return {
            str(key): REDACTED if is_sensitive_key(str(key)) else json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, str):
        return value[:MAX_TEXT_LENGTH]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:MAX_TEXT_LENGTH]


def changed_fields(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The keys whose values differ, from each side. Keeps audit diffs small."""
    keys = [key for key in after if before.get(key) != after[key]]
    return {key: before.get(key) for key in keys}, {key: after[key] for key in keys}


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        action: AuditAction,
        *,
        tenant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        meta: RequestMeta,
        entity_type: str | None = None,
        entity_id: str | uuid.UUID | int | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditLog:
        row = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action.value,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=json_safe(before) if before is not None else None,
            after=json_safe(after) if after is not None else None,
            ip=meta.ip,
            user_agent=meta.user_agent,
            request_id=meta.request_id,
        )
        self.session.add(row)
        self.session.flush()
        return row
