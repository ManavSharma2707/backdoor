"""Tenants, users, refresh tokens and per tenant business settings."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    MONEY,
    TZ,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    UpdatedAtMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)

DEFAULT_PRIORITY_WEIGHTS = '{"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}'


class Tenant(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug"),
        enum_check("business_type", ("fmcg", "medical")),
    )

    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    business_type: Mapped[str] = mapped_column(Text)
    profile_key: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="INR")
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=true())


class User(IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        tenant_unique(),
        enum_check("role", ("owner", "manager", "staff")),
    )

    email: Mapped[str] = mapped_column(CITEXT)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default="owner")
    is_active: Mapped[bool] = mapped_column(server_default=true())
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(TZ)
    last_failed_login_at: Mapped[datetime | None] = mapped_column(TZ)
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    password_changed_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class RefreshToken(IdMixin, TenantMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        composite_fk("user_id", "users"),
        composite_fk("replaced_by_id", "refresh_tokens"),
        tenant_unique(),
        UniqueConstraint("token_hash"),
        enum_check(
            "revoked_reason",
            ("logout", "logout_all", "reuse_detected", "password_change", "expired"),
            nullable=True,
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    issued_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZ, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)
    rotated_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)


class BusinessSettings(UpdatedAtMixin, Base):
    """One row per tenant; the primary key is the tenant id."""

    __tablename__ = "business_settings"
    __table_args__ = (
        enum_check("censor_policy", ("exclude", "weekday_fill")),
        enum_check("pack_rounding", ("up", "nearest_safe")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    weekly_budget: Mapped[Decimal | None] = mapped_column(MONEY)
    service_level: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0.95")
    review_period_days: Mapped[int] = mapped_column(SmallInteger, server_default="7")
    default_lead_time_days: Mapped[int] = mapped_column(SmallInteger, server_default="3")
    near_expiry_days: Mapped[int] = mapped_column(SmallInteger, server_default="90")
    nonmoving_days: Mapped[int] = mapped_column(SmallInteger, server_default="60")
    slow_cover_days: Mapped[int] = mapped_column(SmallInteger, server_default="90")
    excess_horizon_days: Mapped[int] = mapped_column(SmallInteger, server_default="30")
    forecast_horizon_days: Mapped[int] = mapped_column(SmallInteger, server_default="28")
    backtest_origins: Mapped[int] = mapped_column(SmallInteger, server_default="12")
    stale_count_days: Mapped[int] = mapped_column(SmallInteger, server_default="30")
    sellable_shelf_life_fraction: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), server_default="0.60"
    )
    censor_policy: Mapped[str] = mapped_column(Text, server_default="exclude")
    pack_rounding: Mapped[str] = mapped_column(Text, server_default="up")
    priority_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text(f"'{DEFAULT_PRIORITY_WEIGHTS}'::jsonb")
    )
    apply_festival_lead_padding: Mapped[bool] = mapped_column(server_default=true())
    agents_enabled: Mapped[bool] = mapped_column(server_default=true())
