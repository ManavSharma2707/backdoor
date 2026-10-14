"""index for the reversal link between ledger movements

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `reverses_movement_id` is a foreign key to the same table. Without an index every delete
    # from `inventory_movements` scans the whole table once per row (a demo reset took minutes).
    # Only voids set the column, so the partial index stays tiny.
    op.create_index(
        "ix_inventory_movements_tenant_reverses",
        "inventory_movements",
        ["tenant_id", "reverses_movement_id"],
        postgresql_where=sa.text("reverses_movement_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_tenant_reverses", table_name="inventory_movements")
