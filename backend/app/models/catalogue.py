"""Categories, products, prices and retailer defined equivalents."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    PRICE,
    QTY,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    UpdatedAtMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)

BASE_UNITS = (
    "pcs",
    "pack",
    "strip",
    "bottle",
    "tube",
    "sachet",
    "box",
    "kg",
    "litre",
    "vial",
    "tin",
)


class Category(IdMixin, TenantMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        composite_fk("parent_id", "categories"),
        UniqueConstraint("tenant_id", "slug"),
        tenant_unique(),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


class Product(IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        composite_fk("category_id", "categories"),
        UniqueConstraint("tenant_id", "sku"),
        tenant_unique(),
        CheckConstraint("selling_price >= 0 AND mrp >= 0", name="prices_non_negative"),
        enum_check("base_unit", BASE_UNITS),
        enum_check("schedule_class", ("H", "H1", "X"), nullable=True),
        Index("ix_products_tenant_category", "tenant_id", "category_id"),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_sku_trgm",
            "sku",
            postgresql_using="gin",
            postgresql_ops={"sku": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_brand_trgm",
            "brand",
            postgresql_using="gin",
            postgresql_ops={"brand": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_generic_name_trgm",
            "generic_name",
            postgresql_using="gin",
            postgresql_ops={"generic_name": "gin_trgm_ops"},
        ),
    )

    sku: Mapped[str] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    base_unit: Mapped[str] = mapped_column(Text)
    pack_label: Mapped[str | None] = mapped_column(Text)
    tax_rate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tax_rates.id"))
    mrp: Mapped[Decimal] = mapped_column(PRICE)
    selling_price: Mapped[Decimal] = mapped_column(PRICE)
    is_batch_tracked: Mapped[bool] = mapped_column(server_default=text("false"))
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    schedule_class: Mapped[str | None] = mapped_column(Text)
    generic_name: Mapped[str | None] = mapped_column(Text)
    strength: Mapped[str | None] = mapped_column(Text)
    dosage_form: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    min_stock_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    is_seasonal: Mapped[bool] = mapped_column(server_default=text("false"))
    launched_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)


class ProductPrice(IdMixin, TenantMixin, Base):
    __tablename__ = "product_prices"
    __table_args__ = (
        composite_fk("product_id", "products"),
        UniqueConstraint("tenant_id", "product_id", "effective_from"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mrp: Mapped[Decimal] = mapped_column(PRICE)
    selling_price: Mapped[Decimal] = mapped_column(PRICE)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)


class ProductEquivalent(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """Retailer defined link. The system never proposes substitutes."""

    __tablename__ = "product_equivalents"
    __table_args__ = (
        composite_fk("product_id", "products"),
        composite_fk("equivalent_product_id", "products"),
        UniqueConstraint("tenant_id", "product_id", "equivalent_product_id"),
        CheckConstraint("product_id <> equivalent_product_id", name="not_self"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    equivalent_product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
