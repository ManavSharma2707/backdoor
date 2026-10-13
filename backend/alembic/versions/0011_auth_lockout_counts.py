"""lockout window and optional counted quantity

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Lockout counts failures "within 15 minutes", which needs the time of the latest one.
    op.add_column("users", sa.Column("last_failed_login_at", sa.DateTime(timezone=True)))
    # A draft count starts with every line uncounted. NULL means "not counted yet", and the
    # generated variance column is NULL for those lines.
    op.alter_column(
        "stock_count_lines", "counted_qty", existing_type=sa.Numeric(14, 3), nullable=True
    )


def downgrade() -> None:
    op.execute("UPDATE stock_count_lines SET counted_qty = system_qty WHERE counted_qty IS NULL")
    op.alter_column(
        "stock_count_lines", "counted_qty", existing_type=sa.Numeric(14, 3), nullable=False
    )
    op.drop_column("users", "last_failed_login_at")
