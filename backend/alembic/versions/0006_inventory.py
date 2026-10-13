"""inventory

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_counts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("count_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"status\" IN ('draft', 'posted', 'void')", name=op.f("ck_stock_counts_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_stock_counts_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_stock_counts_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_counts")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_stock_counts_tenant_id_id")),
    )
    op.create_table(
        "stockout_intervals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"source\" IN ('recorded', 'inferred')",
            name=op.f("ck_stockout_intervals_source_valid"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_stockout_intervals_end_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_stockout_intervals_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_stockout_intervals_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_stockout_intervals_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stockout_intervals")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "start_date",
            "source",
            name=op.f("uq_stockout_intervals_tenant_id_product_id_start_date_source"),
        ),
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("movement_type", sa.Text(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reverses_movement_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"movement_type\" IN ('opening', 'receipt', 'sale', 'void_reversal', 'return_in', 'damage', 'expiry_writeoff', 'supplier_return', 'adjustment', 'count_correction')",
            name=op.f("ck_inventory_movements_movement_type_valid"),
        ),
        sa.CheckConstraint(
            "\"source_type\" IN ('sale', 'sale_return', 'receipt', 'adjustment', 'stock_count', 'opening', 'void')",
            name=op.f("ck_inventory_movements_source_type_valid"),
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0", name=op.f("ck_inventory_movements_delta_not_zero")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_inventory_movements_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_inventory_movements_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_inventory_movements_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_movement_id"],
            ["inventory_movements.tenant_id", "inventory_movements.id"],
            name=op.f("fk_inventory_movements_tenant_id_reverses_movement_id_inventory_movements"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_inventory_movements_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_movements")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_inventory_movements_tenant_id_id")),
    )
    op.create_index(
        "ix_inventory_movements_tenant_batch",
        "inventory_movements",
        ["tenant_id", "batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_movements_tenant_product_date",
        "inventory_movements",
        ["tenant_id", "product_id", "business_date"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_movements_tenant_source",
        "inventory_movements",
        ["tenant_id", "source_type", "source_id"],
        unique=False,
    )
    op.create_table(
        "stock_balances",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("on_hand", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False),
        sa.Column(
            "reserved_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "avg_unit_cost", sa.Numeric(precision=12, scale=4), server_default="0", nullable=False
        ),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("on_hand >= 0", name=op.f("ck_stock_balances_on_hand_non_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_stock_balances_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_stock_balances_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_stock_balances_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_balances")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "batch_id",
            name=op.f("uq_stock_balances_tenant_id_product_id_batch_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_stock_balances_tenant_product",
        "stock_balances",
        ["tenant_id", "product_id"],
        unique=False,
    )
    op.create_table(
        "stock_count_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("count_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("system_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("counted_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "variance",
            sa.Numeric(precision=14, scale=3),
            sa.Computed("counted_qty - system_qty", persisted=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_stock_count_lines_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "count_id"],
            ["stock_counts.tenant_id", "stock_counts.id"],
            name=op.f("fk_stock_count_lines_tenant_id_count_id_stock_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_stock_count_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_stock_count_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_count_lines")),
        sa.UniqueConstraint(
            "tenant_id",
            "count_id",
            "product_id",
            "batch_id",
            name=op.f("uq_stock_count_lines_tenant_id_count_id_product_id_batch_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "stock_adjustments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("movement_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"reason_code\" IN ('damage', 'expiry_writeoff', 'theft_loss', 'found', 'correction', 'supplier_return', 'other')",
            name=op.f("ck_stock_adjustments_reason_code_valid"),
        ),
        sa.CheckConstraint("quantity_delta <> 0", name=op.f("ck_stock_adjustments_delta_not_zero")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_stock_adjustments_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_stock_adjustments_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "movement_id"],
            ["inventory_movements.tenant_id", "inventory_movements.id"],
            name=op.f("fk_stock_adjustments_tenant_id_movement_id_inventory_movements"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_stock_adjustments_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_stock_adjustments_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_adjustments")),
    )
    op.execute(
        "CREATE TRIGGER trg_stock_balances_set_updated_at BEFORE UPDATE ON stock_balances "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("stock_adjustments")
    op.drop_table("stock_count_lines")
    op.drop_table("stock_balances")
    op.drop_table("inventory_movements")
    op.drop_table("stockout_intervals")
    op.drop_table("stock_counts")
