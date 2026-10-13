"""sales

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("bill_no", sa.Text(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="completed", nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "discount_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "tax_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", sa.UUID(), nullable=True),
        sa.Column("source", sa.Text(), server_default="app", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"payment_mode\" IN ('cash', 'upi', 'card', 'credit')",
            name=op.f("ck_sales_payment_mode_valid"),
        ),
        sa.CheckConstraint(
            "\"source\" IN ('app', 'seed', 'import')", name=op.f("ck_sales_source_valid")
        ),
        sa.CheckConstraint(
            "\"status\" IN ('completed', 'void')", name=op.f("ck_sales_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_sales_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_sales_tenant_id_tenants")
        ),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], name=op.f("fk_sales_voided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
        sa.UniqueConstraint("tenant_id", "bill_no", name=op.f("uq_sales_tenant_id_bill_no")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sales_tenant_id_id")),
    )
    op.create_index(
        "ix_sales_tenant_business_date", "sales", ["tenant_id", "business_date"], unique=False
    )
    op.create_index(
        "uq_sales_tenant_idempotency_key",
        "sales",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "promotions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("discount_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('discount', 'bundle', 'bogo', 'festival_offer')",
            name=op.f("ck_promotions_kind_valid"),
        ),
        sa.CheckConstraint(
            "(product_id IS NULL) <> (category_id IS NULL)", name=op.f("ck_promotions_one_target")
        ),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_promotions_ends_after_start")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_promotions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name=op.f("fk_promotions_tenant_id_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_promotions_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_promotions_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotions")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_promotions_tenant_id_id")),
    )
    op.create_table(
        "sale_returns",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("return_no", sa.Text(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="posted", nullable=False),
        sa.Column("refund_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"status\" IN ('posted', 'void')", name=op.f("ck_sale_returns_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_sale_returns_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sale_id"],
            ["sales.tenant_id", "sales.id"],
            name=op.f("fk_sale_returns_tenant_id_sale_id_sales"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_sale_returns_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_returns")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sale_returns_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "return_no", name=op.f("uq_sale_returns_tenant_id_return_no")
        ),
    )
    op.create_table(
        "sale_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "discount_amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("tax_rate_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("promotion_id", sa.UUID(), nullable=True),
        sa.Column(
            "returned_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_lines_quantity_positive")),
        sa.CheckConstraint(
            "returned_qty <= quantity", name=op.f("ck_sale_lines_returned_within_sold")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_sale_lines_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_sale_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "promotion_id"],
            ["promotions.tenant_id", "promotions.id"],
            name=op.f("fk_sale_lines_tenant_id_promotion_id_promotions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sale_id"],
            ["sales.tenant_id", "sales.id"],
            name=op.f("fk_sale_lines_tenant_id_sale_id_sales"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_sale_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_lines")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sale_lines_tenant_id_id")),
    )
    op.create_index(
        "ix_sale_lines_tenant_product_date",
        "sale_lines",
        ["tenant_id", "product_id", "business_date"],
        unique=False,
    )
    op.create_index(
        "ix_sale_lines_tenant_sale", "sale_lines", ["tenant_id", "sale_id"], unique=False
    )
    op.create_table(
        "sale_return_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("return_id", sa.UUID(), nullable=False),
        sa.Column("sale_line_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("refund_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "\"disposition\" IN ('restock', 'damaged', 'expired')",
            name=op.f("ck_sale_return_lines_disposition_valid"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_return_lines_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["product_batches.tenant_id", "product_batches.id"],
            name=op.f("fk_sale_return_lines_tenant_id_batch_id_product_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_sale_return_lines_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "return_id"],
            ["sale_returns.tenant_id", "sale_returns.id"],
            name=op.f("fk_sale_return_lines_tenant_id_return_id_sale_returns"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sale_line_id"],
            ["sale_lines.tenant_id", "sale_lines.id"],
            name=op.f("fk_sale_return_lines_tenant_id_sale_line_id_sale_lines"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_sale_return_lines_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_return_lines")),
    )
    op.create_index(
        "ix_sale_return_lines_tenant_return",
        "sale_return_lines",
        ["tenant_id", "return_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("sale_return_lines")
    op.drop_table("sale_lines")
    op.drop_table("sale_returns")
    op.drop_table("promotions")
    op.drop_table("sales")
