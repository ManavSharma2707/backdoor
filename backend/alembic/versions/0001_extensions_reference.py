"""extensions reference

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for extension in ("vector", "citext", "pg_trgm", "pgcrypto"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
        """
    )
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("pre_window_days", sa.SmallInteger(), server_default="7", nullable=False),
        sa.Column("post_window_days", sa.SmallInteger(), server_default="3", nullable=False),
        sa.Column("delivery_delay_days", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("affects_hours", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("region_scope", sa.Text(), server_default="maharashtra", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('festival', 'season', 'holiday')",
            name=op.f("ck_calendar_events_kind_valid"),
        ),
        sa.CheckConstraint(
            "end_date >= start_date", name=op.f("ck_calendar_events_end_after_start")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_events")),
        sa.UniqueConstraint(
            "event_key", "start_date", name=op.f("uq_calendar_events_event_key_start_date")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_calendar_events_slug")),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_model_versions_name_version")),
    )
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("rate_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tax_rates")),
        sa.UniqueConstraint("code", name=op.f("uq_tax_rates_code")),
    )


def downgrade() -> None:
    op.drop_table("tax_rates")
    op.drop_table("model_versions")
    op.drop_table("calendar_events")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    for extension in ("pgcrypto", "pg_trgm", "citext", "vector"):
        op.execute(f"DROP EXTENSION IF EXISTS {extension}")
