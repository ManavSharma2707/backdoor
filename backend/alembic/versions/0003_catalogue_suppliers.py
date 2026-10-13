"""catalogue suppliers

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["categories.tenant_id", "categories.id"],
            name=op.f("fk_categories_tenant_id_parent_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_categories_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_categories_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "slug", name=op.f("uq_categories_tenant_id_slug")),
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("payment_terms_days", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("default_lead_time_days", sa.SmallInteger(), nullable=True),
        sa.Column("delivery_weekdays", sa.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("min_order_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("credit_limit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "accepts_expiry_returns", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("expiry_return_window_days", sa.SmallInteger(), nullable=True),
        sa.Column("return_window_days", sa.SmallInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "delivery_weekdays IS NULL OR delivery_weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[]",
            name=op.f("ck_suppliers_delivery_weekdays_iso"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_suppliers_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_suppliers_tenant_id_code")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_suppliers_tenant_id_id")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("base_unit", sa.Text(), nullable=False),
        sa.Column("pack_label", sa.Text(), nullable=True),
        sa.Column("tax_rate_id", sa.UUID(), nullable=False),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "is_batch_tracked", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("shelf_life_days", sa.Integer(), nullable=True),
        sa.Column("schedule_class", sa.Text(), nullable=True),
        sa.Column("generic_name", sa.Text(), nullable=True),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.Column("dosage_form", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.Text(), nullable=True),
        sa.Column(
            "min_stock_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("is_seasonal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("launched_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "\"base_unit\" IN ('pcs', 'pack', 'strip', 'bottle', 'tube', 'sachet', 'box', 'kg', 'litre', 'vial', 'tin')",
            name=op.f("ck_products_base_unit_valid"),
        ),
        sa.CheckConstraint(
            "\"schedule_class\" IS NULL OR \"schedule_class\" IN ('H', 'H1', 'X')",
            name=op.f("ck_products_schedule_class_valid"),
        ),
        sa.CheckConstraint(
            "selling_price >= 0 AND mrp >= 0", name=op.f("ck_products_prices_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id"], ["tax_rates.id"], name=op.f("fk_products_tax_rate_id_tax_rates")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name=op.f("fk_products_tenant_id_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_products_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_products_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "sku", name=op.f("uq_products_tenant_id_sku")),
    )
    op.create_index(
        "ix_products_brand_trgm",
        "products",
        ["brand"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"brand": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_products_generic_name_trgm",
        "products",
        ["generic_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"generic_name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_products_name_trgm",
        "products",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_products_sku_trgm",
        "products",
        ["sku"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"sku": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_products_tenant_category", "products", ["tenant_id", "category_id"], unique=False
    )
    op.create_table(
        "product_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("batch_no", sa.Text(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("manufactured_on", sa.Date(), nullable=True),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("initial_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"status\" IN ('active', 'quarantined', 'expired', 'closed')",
            name=op.f("ck_product_batches_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_product_batches_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_product_batches_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_batches")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_product_batches_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "batch_no",
            name=op.f("uq_product_batches_tenant_id_product_id_batch_no"),
        ),
    )
    op.create_index(
        "ix_product_batches_tenant_expiry",
        "product_batches",
        ["tenant_id", "expiry_date"],
        unique=False,
    )
    op.create_table(
        "product_equivalents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("equivalent_product_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "product_id <> equivalent_product_id", name=op.f("ck_product_equivalents_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_product_equivalents_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "equivalent_product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_product_equivalents_tenant_id_equivalent_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_product_equivalents_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_product_equivalents_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_equivalents")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "equivalent_product_id",
            name=op.f("uq_product_equivalents_tenant_id_product_id_equivalent_product_id"),
        ),
    )
    op.create_table(
        "product_prices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_product_prices_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_product_prices_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_prices")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "effective_from",
            name=op.f("uq_product_prices_tenant_id_product_id_effective_from"),
        ),
    )
    op.create_table(
        "supplier_product_terms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("purchase_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "pack_size", sa.Numeric(precision=14, scale=3), server_default="1", nullable=False
        ),
        sa.Column(
            "moq_units", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("lead_time_days", sa.SmallInteger(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pack_size > 0", name=op.f("ck_supplier_product_terms_pack_size_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_supplier_product_terms_tenant_id_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name=op.f("fk_supplier_product_terms_tenant_id_supplier_id_suppliers"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_supplier_product_terms_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_product_terms")),
        sa.UniqueConstraint(
            "tenant_id",
            "supplier_id",
            "product_id",
            "effective_from",
            name=op.f("uq_supplier_product_terms_tenant_id_supplier_id_product_id_effective_from"),
        ),
    )
    op.create_index(
        "uq_supplier_product_terms_one_primary",
        "supplier_product_terms",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND effective_to IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_suppliers_set_updated_at BEFORE UPDATE ON suppliers "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_products_set_updated_at BEFORE UPDATE ON products "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("supplier_product_terms")
    op.drop_table("product_prices")
    op.drop_table("product_equivalents")
    op.drop_table("product_batches")
    op.drop_table("products")
    op.drop_table("suppliers")
    op.drop_table("categories")
