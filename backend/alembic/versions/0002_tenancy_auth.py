"""tenancy auth

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("business_type", sa.Text(), nullable=False),
        sa.Column("profile_key", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), server_default="Asia/Kolkata", nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default="INR", nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"business_type\" IN ('fmcg', 'medical')", name=op.f("ck_tenants_business_type_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "business_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("weekly_budget", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "service_level", sa.Numeric(precision=4, scale=3), server_default="0.95", nullable=False
        ),
        sa.Column("review_period_days", sa.SmallInteger(), server_default="7", nullable=False),
        sa.Column("default_lead_time_days", sa.SmallInteger(), server_default="3", nullable=False),
        sa.Column("near_expiry_days", sa.SmallInteger(), server_default="90", nullable=False),
        sa.Column("nonmoving_days", sa.SmallInteger(), server_default="60", nullable=False),
        sa.Column("slow_cover_days", sa.SmallInteger(), server_default="90", nullable=False),
        sa.Column("excess_horizon_days", sa.SmallInteger(), server_default="30", nullable=False),
        sa.Column("forecast_horizon_days", sa.SmallInteger(), server_default="28", nullable=False),
        sa.Column("backtest_origins", sa.SmallInteger(), server_default="12", nullable=False),
        sa.Column("stale_count_days", sa.SmallInteger(), server_default="30", nullable=False),
        sa.Column(
            "sellable_shelf_life_fraction",
            sa.Numeric(precision=3, scale=2),
            server_default="0.60",
            nullable=False,
        ),
        sa.Column("censor_policy", sa.Text(), server_default="exclude", nullable=False),
        sa.Column("pack_rounding", sa.Text(), server_default="up", nullable=False),
        sa.Column(
            "priority_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column(
            "apply_festival_lead_padding",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("agents_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"censor_policy\" IN ('exclude', 'weekday_fill')",
            name=op.f("ck_business_settings_censor_policy_valid"),
        ),
        sa.CheckConstraint(
            "\"pack_rounding\" IN ('up', 'nearest_safe')",
            name=op.f("ck_business_settings_pack_rounding_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_business_settings_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_business_settings")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="owner", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"role\" IN ('owner', 'manager', 'staff')", name=op.f("ck_users_role_valid")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_users_tenant_id_id")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("replaced_by_id", sa.UUID(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.CheckConstraint(
            "\"revoked_reason\" IS NULL OR \"revoked_reason\" IN ('logout', 'logout_all', 'reuse_detected', 'password_change', 'expired')",
            name=op.f("ck_refresh_tokens_revoked_reason_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "replaced_by_id"],
            ["refresh_tokens.tenant_id", "refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_tenant_id_replaced_by_id_refresh_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_refresh_tokens_tenant_id_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_refresh_tokens_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_refresh_tokens_tenant_id_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.execute(
        "CREATE TRIGGER trg_tenants_set_updated_at BEFORE UPDATE ON tenants "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_business_settings_set_updated_at BEFORE UPDATE ON business_settings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_users_set_updated_at BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("business_settings")
    op.drop_table("tenants")
