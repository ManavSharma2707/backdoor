"""purchasing

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("po_number", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "subtotal_estimated",
            sa.Numeric(precision=14, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("source", sa.Text(), server_default="manual", nullable=False),
        sa.Column("recommendation_run_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
            "\"source\" IN ('manual', 'recommendation', 'seed')",
            name=op.f("ck_purchase_orders_source_valid"),
        ),
        sa.CheckConstraint(
            "\"status\" IN ('draft', 'sent', 'partially_received', 'received', 'cancelled', 'closed')",
            name=op.f("ck_purchase_orders_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_purchase_orders_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name=op.f("fk_purchase_orders_tenant_id_supplier_id_suppliers"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_purchase_orders_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_purchase_orders_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "po_number", name=op.f("uq_purchase_orders_tenant_id_po_number")
        ),
    )
    op.create_index(
        "ix_purchase_orders_tenant_status_expected",
        "purchase_orders",
        ["tenant_id", "status", "expected_date"],
        unique=False,
    )
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("purchase_order_id", sa.UUID(), nullable=True),
        sa.Column("receipt_no", sa.Text(), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("invoice_no", sa.Text(), nullable=True),
        sa.Column("invoice_total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("status", sa.Text(), server_default="posted", nullable=False),
        sa.Column("is_exception", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("exception_note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"status\" IN ('posted', 'void')", name=op.f("ck_goods_receipts_status_valid")
        ),
        sa.CheckConstraint(
            "NOT is_exception OR exception_note IS NOT NULL",
            name=op.f("ck_goods_receipts_exception_needs_note"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_goods_receipts_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "purchase_order_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name=op.f("fk_goods_receipts_tenant_id_purchase_order_id_purchase_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name=op.f("fk_goods_receipts_tenant_id_supplier_id_suppliers"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_goods_receipts_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipts")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_goods_receipts_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "receipt_no", name=op.f("uq_goods_receipts_tenant_id_receipt_no")
        ),
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("po_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("quantity_ordered", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("pack_size", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "quantity_received",
            sa.Numeric(precision=14, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column("recommendation_line_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_ordered > 0", name=op.f("ck_purchase_order_lines_quantity_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "po_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name=op.f("fk_purchase_order_lines_tenant_id_po_id_purchase_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_purchase_order_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_purchase_order_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_lines")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_purchase_order_lines_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "po_id",
            "product_id",
            name=op.f("uq_purchase_order_lines_tenant_id_po_id_product_id"),
        ),
    )
    op.create_table(
        "receipt_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("receipt_id", sa.UUID(), nullable=False),
        sa.Column("po_line_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("quantity_received", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_received > 0", name=op.f("ck_receipt_lines_quantity_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_receipt_lines_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "po_line_id"],
            ["purchase_order_lines.tenant_id", "purchase_order_lines.id"],
            name=op.f("fk_receipt_lines_tenant_id_po_line_id_purchase_order_lines"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_receipt_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["goods_receipts.tenant_id", "goods_receipts.id"],
            name=op.f("fk_receipt_lines_tenant_id_receipt_id_goods_receipts"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_receipt_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt_lines")),
    )
    op.create_index(
        "ix_receipt_lines_tenant_receipt",
        "receipt_lines",
        ["tenant_id", "receipt_id"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER trg_purchase_orders_set_updated_at BEFORE UPDATE ON purchase_orders "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("receipt_lines")
    op.drop_table("purchase_order_lines")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_orders")
