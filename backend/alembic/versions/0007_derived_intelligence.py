"""derived intelligence

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger(), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "\"kind\" IN ('weekly', 'backtest', 'adhoc')", name=op.f("ck_forecast_runs_kind_valid")
        ),
        sa.CheckConstraint(
            "\"profile\" IN ('light', 'full')", name=op.f("ck_forecast_runs_profile_valid")
        ),
        sa.CheckConstraint(
            "\"status\" IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_forecast_runs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_forecast_runs_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_forecast_runs_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_forecast_runs_tenant_id_id")),
    )
    op.create_index(
        "ix_forecast_runs_tenant_as_of_date",
        "forecast_runs",
        ["tenant_id", sa.literal_column("as_of_date DESC")],
        unique=False,
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fix_hint", sa.Text(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "\"severity\" IN ('info', 'warning', 'error')",
            name=op.f("ck_data_quality_issues_severity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_data_quality_issues_resolved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_data_quality_issues_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_issues")),
    )
    op.create_index(
        "uq_data_quality_issues_open",
        "data_quality_issues",
        ["tenant_id", "code", "entity_type", "entity_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_table(
        "event_category_effects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("window", sa.Text(), nullable=False),
        sa.Column("multiplier", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("n_occurrences", sa.SmallInteger(), nullable=False),
        sa.Column("n_products", sa.SmallInteger(), nullable=False),
        sa.Column("consistency", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("is_applied", sa.Boolean(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"confidence\" IN ('high', 'medium', 'low')",
            name=op.f("ck_event_category_effects_confidence_valid"),
        ),
        sa.CheckConstraint(
            "\"origin\" IN ('learned', 'configured')",
            name=op.f("ck_event_category_effects_origin_valid"),
        ),
        sa.CheckConstraint(
            "\"window\" IN ('pre', 'during', 'post')",
            name=op.f("ck_event_category_effects_window_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name=op.f("fk_event_category_effects_tenant_id_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_event_category_effects_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_category_effects")),
        sa.UniqueConstraint(
            "tenant_id",
            "event_key",
            "category_id",
            "window",
            "origin",
            name=op.f("uq_event_category_effects_tenant_id_event_key_category_id_window_origin"),
        ),
    )
    op.create_table(
        "forecast_backtests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scope_key", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("n_folds", sa.SmallInteger(), nullable=False),
        sa.Column("n_points", sa.Integer(), nullable=False),
        sa.Column("mae", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("wape", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("bias", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("rmse", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("coverage_ratio", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("is_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"scope\" IN ('product', 'segment', 'tenant')",
            name=op.f("ck_forecast_backtests_scope_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["forecast_runs.tenant_id", "forecast_runs.id"],
            name=op.f("fk_forecast_backtests_tenant_id_run_id_forecast_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_forecast_backtests_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_backtests")),
    )
    op.create_index(
        "ix_forecast_backtests_tenant_run_scope",
        "forecast_backtests",
        ["tenant_id", "run_id", "scope"],
        unique=False,
    )
    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("forecast_run_id", sa.UUID(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("budget", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "settings_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "\"status\" IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_recommendation_runs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_recommendation_runs_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "forecast_run_id"],
            ["forecast_runs.tenant_id", "forecast_runs.id"],
            name=op.f("fk_recommendation_runs_tenant_id_forecast_run_id_forecast_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_recommendation_runs_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_recommendation_runs_tenant_id_id")),
    )
    op.create_table(
        "daily_product_stats",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("units_sold", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("units_returned", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("revenue", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("avg_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("opening_on_hand", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("closing_on_hand", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("receipts_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("availability_state", sa.Text(), nullable=False),
        sa.Column("is_censored", sa.Boolean(), nullable=False),
        sa.Column("promo_active", sa.Boolean(), nullable=False),
        sa.Column(
            "event_keys",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"availability_state\" IN ('available', 'stocked_out_all_day', 'sold_out_during_day', 'not_launched', 'unknown')",
            name=op.f("ck_daily_product_stats_availability_state_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_daily_product_stats_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_daily_product_stats_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "product_id", "stat_date", name=op.f("pk_daily_product_stats")
        ),
    )
    op.create_index(
        "ix_daily_product_stats_tenant_date",
        "daily_product_stats",
        ["tenant_id", "stat_date"],
        unique=False,
    )
    op.create_table(
        "forecast_values",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("yhat", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("yhat_lower", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("yhat_upper", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column(
            "event_multiplier", sa.Numeric(precision=6, scale=3), server_default="1", nullable=False
        ),
        sa.Column("event_key", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_forecast_values_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["forecast_runs.tenant_id", "forecast_runs.id"],
            name=op.f("fk_forecast_values_tenant_id_run_id_forecast_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_forecast_values_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_values")),
        sa.UniqueConstraint(
            "run_id",
            "product_id",
            "forecast_date",
            name=op.f("uq_forecast_values_run_id_product_id_forecast_date"),
        ),
    )
    op.create_table(
        "recommendation_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=True),
        sa.Column("sections", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("protection_days", sa.SmallInteger(), nullable=False),
        sa.Column("lead_time_days", sa.SmallInteger(), nullable=False),
        sa.Column("lead_time_source", sa.Text(), nullable=False),
        sa.Column("avg_daily_forecast", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("demand_7d", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("demand_protection", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("on_hand_usable", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "expected_expiry_loss",
            sa.Numeric(precision=14, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "incoming_confirmed",
            sa.Numeric(precision=14, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "incoming_excluded_overdue",
            sa.Numeric(precision=14, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reserved", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("inventory_position", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("safety_stock", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("target_level", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("raw_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("moq_units", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("pack_size", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("suggested_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("allocated_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "pack_excess_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("est_spend", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "unfunded_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("budget_limited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("stockout_probability", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("projected_stockout_date", sa.Date(), nullable=True),
        sa.Column("days_of_cover", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("risk_level", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("forecast_method", sa.Text(), nullable=False),
        sa.Column("wape", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("priority_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("priority_components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "expiry_exposure_qty",
            sa.Numeric(precision=14, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "expiry_exposure_value",
            sa.Numeric(precision=14, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "excess_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "excess_value", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("stock_status", sa.Text(), nullable=True),
        sa.Column(
            "event_keys",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "reason_codes",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sections <@ ARRAY['buy','do_not_buy','watch','reduce']::text[]",
            name=op.f("ck_recommendation_lines_sections_valid"),
        ),
        sa.CheckConstraint(
            "\"confidence\" IN ('high', 'medium', 'low')",
            name=op.f("ck_recommendation_lines_confidence_valid"),
        ),
        sa.CheckConstraint(
            "\"lead_time_source\" IN ('product_term', 'supplier_default', 'business_default')",
            name=op.f("ck_recommendation_lines_lead_time_source_valid"),
        ),
        sa.CheckConstraint(
            "\"risk_level\" IN ('critical', 'high', 'medium', 'low', 'none')",
            name=op.f("ck_recommendation_lines_risk_level_valid"),
        ),
        sa.CheckConstraint(
            "\"stock_status\" IS NULL OR \"stock_status\" IN ('slow', 'non_moving', 'unverified', 'normal', 'new')",
            name=op.f("ck_recommendation_lines_stock_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_recommendation_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["recommendation_runs.tenant_id", "recommendation_runs.id"],
            name=op.f("fk_recommendation_lines_tenant_id_run_id_recommendation_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name=op.f("fk_recommendation_lines_tenant_id_supplier_id_suppliers"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_recommendation_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_lines")),
        sa.UniqueConstraint(
            "run_id", "product_id", name=op.f("uq_recommendation_lines_run_id_product_id")
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_recommendation_lines_tenant_id_id")),
    )
    op.create_index(
        "ix_recommendation_lines_tenant_run_risk",
        "recommendation_lines",
        ["tenant_id", "run_id", "risk_level"],
        unique=False,
    )
    op.create_table(
        "synthetic_true_demand",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("true_demand", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("event_multiplier", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("promo_multiplier", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_synthetic_true_demand_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_synthetic_true_demand_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "product_id", "stat_date", name=op.f("pk_synthetic_true_demand")
        ),
    )
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("recommendation_run_id", sa.UUID(), nullable=False),
        sa.Column("forecast_run_id", sa.UUID(), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("agent_review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "\"status\" IN ('generating', 'ready', 'failed')",
            name=op.f("ck_weekly_reports_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "forecast_run_id"],
            ["forecast_runs.tenant_id", "forecast_runs.id"],
            name=op.f("fk_weekly_reports_tenant_id_forecast_run_id_forecast_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recommendation_run_id"],
            ["recommendation_runs.tenant_id", "recommendation_runs.id"],
            name=op.f("fk_weekly_reports_tenant_id_recommendation_run_id_recommendation_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_weekly_reports_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_reports")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_weekly_reports_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "week_start",
            "version",
            name=op.f("uq_weekly_reports_tenant_id_week_start_version"),
        ),
    )
    op.create_index(
        "uq_weekly_reports_current_week",
        "weekly_reports",
        ["tenant_id", "week_start"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("line_id", sa.UUID(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("final_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"decision\" IN ('approved', 'edited', 'rejected')",
            name=op.f("ck_recommendation_decisions_decision_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_recommendation_decisions_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["recommendation_lines.tenant_id", "recommendation_lines.id"],
            name=op.f("fk_recommendation_decisions_tenant_id_line_id_recommendation_lines"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_recommendation_decisions_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_decisions")),
    )
    op.create_index(
        "uq_recommendation_decisions_live",
        "recommendation_decisions",
        ["line_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_table(
        "report_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("line_id", sa.UUID(), nullable=True),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"source\" IN ('user', 'agent', 'chat_pin')", name=op.f("ck_report_notes_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], name=op.f("fk_report_notes_author_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["recommendation_lines.tenant_id", "recommendation_lines.id"],
            name=op.f("fk_report_notes_tenant_id_line_id_recommendation_lines"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["weekly_reports.tenant_id", "weekly_reports.id"],
            name=op.f("fk_report_notes_tenant_id_report_id_weekly_reports"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_report_notes_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_notes")),
    )
    op.execute(
        "CREATE TRIGGER trg_daily_product_stats_set_updated_at BEFORE UPDATE ON daily_product_stats "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("report_notes")
    op.drop_table("recommendation_decisions")
    op.drop_table("weekly_reports")
    op.drop_table("synthetic_true_demand")
    op.drop_table("recommendation_lines")
    op.drop_table("forecast_values")
    op.drop_table("daily_product_stats")
    op.drop_table("recommendation_runs")
    op.drop_table("forecast_backtests")
    op.drop_table("event_category_effects")
    op.drop_table("data_quality_issues")
    op.drop_table("forecast_runs")
