"""Job runs, the immutable audit log and idempotency keys."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TZ, Base, CreatedAtMixin, IdMixin, TenantMixin, enum_check


class JobRun(IdMixin, Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("job_name", "run_key", "tenant_id", postgresql_nulls_not_distinct=True),
        enum_check("status", ("running", "succeeded", "failed", "skipped")),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    job_name: Mapped[str] = mapped_column(Text)
    run_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="1")
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(CreatedAtMixin, Base):
    """Append only. A trigger rejects UPDATE, DELETE and TRUNCATE.

    `tenant_id` and `user_id` are plain columns, not foreign keys, so the log outlives a demo
    reset and never blocks deleting a tenant.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", desc("created_at")),
        Index("ix_audit_logs_tenant_action", "tenant_id", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "endpoint"),)

    key: Mapped[str] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    response_status: Mapped[int] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(TZ)
