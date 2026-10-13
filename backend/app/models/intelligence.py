"""Derived data, forecasts, plans (recommendations), reports and data quality issues."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    EMPTY_ARRAY,
    EMPTY_OBJECT,
    EMPTY_TEXT_ARRAY,
    MONEY,
    QTY,
    TZ,
    UNIT_COST,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    UpdatedAtMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)

RUN_STATUSES = ("running", "succeeded", "failed")
RISK_LEVELS = ("critical", "high", "medium", "low", "none")
CONFIDENCE_LEVELS = ("high", "medium", "low")
AVAILABILITY_STATES = (
    "available",
    "stocked_out_all_day",
    "sold_out_during_day",
    "not_launched",
    "unknown",
)
PLAN_SECTIONS = ("buy", "do_not_buy", "watch", "reduce")
STOCK_STATUSES = ("slow", "non_moving", "unverified", "normal", "new")


class DailyProductStat(UpdatedAtMixin, Base):
    """Rebuildable per product per day feature table."""

    __tablename__ = "daily_product_stats"
    __table_args__ = (
        composite_fk("product_id", "products"),
        enum_check("availability_state", AVAILABILITY_STATES),
        Index("ix_daily_product_stats_tenant_date", "tenant_id", "stat_date"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True, sort_order=-90
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    units_sold: Mapped[Decimal] = mapped_column(QTY)
    units_returned: Mapped[Decimal] = mapped_column(QTY)
    revenue: Mapped[Decimal] = mapped_column(MONEY)
    avg_price: Mapped[Decimal | None] = mapped_column(UNIT_COST)
    opening_on_hand: Mapped[Decimal] = mapped_column(QTY)
    closing_on_hand: Mapped[Decimal] = mapped_column(QTY)
    receipts_qty: Mapped[Decimal] = mapped_column(QTY)
    availability_state: Mapped[str] = mapped_column(Text)
    is_censored: Mapped[bool] = mapped_column(Boolean)
    promo_active: Mapped[bool] = mapped_column(Boolean)
    event_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=EMPTY_TEXT_ARRAY)


class SyntheticTrueDemand(Base):
    """Seed only. Read by evaluation scripts, never by product code paths."""

    __tablename__ = "synthetic_true_demand"
    __table_args__ = (composite_fk("product_id", "products"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True, sort_order=-90
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    true_demand: Mapped[Decimal] = mapped_column(QTY)
    event_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    promo_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))


class ForecastRun(IdMixin, TenantMixin, Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        tenant_unique(),
        enum_check("kind", ("weekly", "backtest", "adhoc")),
        enum_check("profile", ("light", "full")),
        enum_check("status", RUN_STATUSES),
        Index("ix_forecast_runs_tenant_as_of_date", "tenant_id", desc("as_of_date")),
    )

    kind: Mapped[str] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(Text)
    data_cutoff: Mapped[datetime] = mapped_column(TZ)
    as_of_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(SmallInteger)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    error: Mapped[str | None] = mapped_column(Text)


class ForecastValue(TenantMixin, Base):
    __tablename__ = "forecast_values"
    __table_args__ = (
        composite_fk("run_id", "forecast_runs"),
        composite_fk("product_id", "products"),
        UniqueConstraint("run_id", "product_id", "forecast_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    forecast_date: Mapped[date] = mapped_column(Date)
    yhat: Mapped[Decimal] = mapped_column(QTY)
    yhat_lower: Mapped[Decimal] = mapped_column(QTY)
    yhat_upper: Mapped[Decimal] = mapped_column(QTY)
    method: Mapped[str] = mapped_column(Text)
    event_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), server_default="1")
    event_key: Mapped[str | None] = mapped_column(Text)


class ForecastBacktest(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "forecast_backtests"
    __table_args__ = (
        composite_fk("run_id", "forecast_runs"),
        enum_check("scope", ("product", "segment", "tenant")),
        Index("ix_forecast_backtests_tenant_run_scope", "tenant_id", "run_id", "scope"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    scope: Mapped[str] = mapped_column(Text)
    scope_key: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    n_folds: Mapped[int] = mapped_column(SmallInteger)
    n_points: Mapped[int] = mapped_column(Integer)
    mae: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    wape: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    bias: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rmse: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    coverage_ratio: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    is_selected: Mapped[bool] = mapped_column(server_default=text("false"))
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EventCategoryEffect(IdMixin, TenantMixin, Base):
    __tablename__ = "event_category_effects"
    __table_args__ = (
        composite_fk("category_id", "categories"),
        UniqueConstraint("tenant_id", "event_key", "category_id", "window", "origin"),
        enum_check("window", ("pre", "during", "post")),
        enum_check("origin", ("learned", "configured")),
        enum_check("confidence", CONFIDENCE_LEVELS),
    )

    event_key: Mapped[str] = mapped_column(Text)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    window: Mapped[str] = mapped_column(Text)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    origin: Mapped[str] = mapped_column(Text)
    n_occurrences: Mapped[int] = mapped_column(SmallInteger)
    n_products: Mapped[int] = mapped_column(SmallInteger)
    consistency: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    confidence: Mapped[str] = mapped_column(Text)
    is_applied: Mapped[bool] = mapped_column(Boolean)
    computed_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class RecommendationRun(IdMixin, TenantMixin, Base):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        composite_fk("forecast_run_id", "forecast_runs"),
        tenant_unique(),
        enum_check("status", RUN_STATUSES),
    )

    forecast_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    as_of_date: Mapped[date] = mapped_column(Date)
    data_cutoff: Mapped[datetime] = mapped_column(TZ)
    budget: Mapped[Decimal | None] = mapped_column(MONEY)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    error: Mapped[str | None] = mapped_column(Text)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id")
    )


class RecommendationLine(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "recommendation_lines"
    __table_args__ = (
        composite_fk("run_id", "recommendation_runs"),
        composite_fk("product_id", "products"),
        composite_fk("supplier_id", "suppliers"),
        UniqueConstraint("run_id", "product_id"),
        tenant_unique(),
        enum_check("lead_time_source", ("product_term", "supplier_default", "business_default")),
        enum_check("risk_level", RISK_LEVELS),
        enum_check("confidence", CONFIDENCE_LEVELS),
        enum_check("stock_status", STOCK_STATUSES, nullable=True),
        CheckConstraint(
            "sections <@ ARRAY['buy','do_not_buy','watch','reduce']::text[]", name="sections_valid"
        ),
        Index("ix_recommendation_lines_tenant_run_risk", "tenant_id", "run_id", "risk_level"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sections: Mapped[list[str]] = mapped_column(ARRAY(Text))
    protection_days: Mapped[int] = mapped_column(SmallInteger)
    lead_time_days: Mapped[int] = mapped_column(SmallInteger)
    lead_time_source: Mapped[str] = mapped_column(Text)
    avg_daily_forecast: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    demand_7d: Mapped[Decimal] = mapped_column(QTY)
    demand_protection: Mapped[Decimal] = mapped_column(QTY)
    on_hand_usable: Mapped[Decimal] = mapped_column(QTY)
    expected_expiry_loss: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    incoming_confirmed: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    incoming_excluded_overdue: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    reserved: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    inventory_position: Mapped[Decimal] = mapped_column(QTY)
    safety_stock: Mapped[Decimal] = mapped_column(QTY)
    target_level: Mapped[Decimal] = mapped_column(QTY)
    raw_qty: Mapped[Decimal] = mapped_column(QTY)
    moq_units: Mapped[Decimal] = mapped_column(QTY)
    pack_size: Mapped[Decimal] = mapped_column(QTY)
    suggested_qty: Mapped[Decimal] = mapped_column(QTY)
    allocated_qty: Mapped[Decimal] = mapped_column(QTY)
    pack_excess_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    unit_cost: Mapped[Decimal | None] = mapped_column(UNIT_COST)
    est_spend: Mapped[Decimal | None] = mapped_column(MONEY)
    unfunded_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    budget_limited: Mapped[bool] = mapped_column(server_default=text("false"))
    stockout_probability: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    projected_stockout_date: Mapped[date | None] = mapped_column(Date)
    days_of_cover: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    risk_level: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    forecast_method: Mapped[str] = mapped_column(Text)
    wape: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    priority_components: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expiry_exposure_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    expiry_exposure_value: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    excess_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    excess_value: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    stock_status: Mapped[str | None] = mapped_column(Text)
    event_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=EMPTY_TEXT_ARRAY)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=EMPTY_TEXT_ARRAY)
    reason_text: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=EMPTY_TEXT_ARRAY)


class RecommendationDecision(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """Append only. The live decision of a line is the one that is not superseded."""

    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        composite_fk("line_id", "recommendation_lines"),
        enum_check("decision", ("approved", "edited", "rejected")),
        Index(
            "uq_recommendation_decisions_live",
            "line_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(Text)
    final_qty: Mapped[Decimal] = mapped_column(QTY)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_text: Mapped[str | None] = mapped_column(Text)
    superseded_at: Mapped[datetime | None] = mapped_column(TZ)


class WeeklyReport(IdMixin, TenantMixin, Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (
        composite_fk("recommendation_run_id", "recommendation_runs"),
        composite_fk("forecast_run_id", "forecast_runs"),
        UniqueConstraint("tenant_id", "week_start", "version"),
        tenant_unique(),
        enum_check("status", ("generating", "ready", "failed")),
        Index(
            "uq_weekly_reports_current_week",
            "tenant_id",
            "week_start",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    week_start: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    is_current: Mapped[bool] = mapped_column(server_default=true())
    recommendation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    data_cutoff: Mapped[datetime] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_ARRAY)
    model_version: Mapped[str] = mapped_column(Text)
    agent_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    error: Mapped[str | None] = mapped_column(Text)


class ReportNote(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "report_notes"
    __table_args__ = (
        composite_fk("report_id", "weekly_reports"),
        composite_fk("line_id", "recommendation_lines"),
        enum_check("source", ("user", "agent", "chat_pin")),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    source: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)


class DataQualityIssue(IdMixin, TenantMixin, Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        enum_check("severity", ("info", "warning", "error")),
        Index(
            "uq_data_quality_issues_open",
            "tenant_id",
            "code",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    # A pipeline run id. Plain uuid, because the DQ step runs before any plan row exists.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fix_hint: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
