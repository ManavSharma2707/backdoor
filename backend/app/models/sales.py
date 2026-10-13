"""Promotions, bills, bill lines and returns."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    MONEY,
    QTY,
    TZ,
    UNIT_COST,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)


class Promotion(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "promotions"
    __table_args__ = (
        composite_fk("product_id", "products"),
        composite_fk("category_id", "categories"),
        tenant_unique(),
        enum_check("kind", ("discount", "bundle", "bogo", "festival_offer")),
        CheckConstraint("(product_id IS NULL) <> (category_id IS NULL)", name="one_target"),
        CheckConstraint("ends_on >= starts_on", name="ends_after_start"),
    )

    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Sale(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bill_no"),
        tenant_unique(),
        enum_check("payment_mode", ("cash", "upi", "card", "credit")),
        enum_check("status", ("completed", "void")),
        enum_check("source", ("app", "seed", "import")),
        Index(
            "uq_sales_tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_sales_tenant_business_date", "tenant_id", "business_date"),
    )

    bill_no: Mapped[str] = mapped_column(Text)
    business_date: Mapped[date] = mapped_column(Date)
    sold_at: Mapped[datetime] = mapped_column(TZ)
    payment_mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="completed")
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    total: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(TZ)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(Text, server_default="app")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class SaleLine(TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "sale_lines"
    __table_args__ = (
        composite_fk("sale_id", "sales"),
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        composite_fk("promotion_id", "promotions"),
        tenant_unique(),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("returned_qty <= quantity", name="returned_within_sold"),
        Index("ix_sale_lines_tenant_product_date", "tenant_id", "product_id", "business_date"),
        Index("ix_sale_lines_tenant_sale", "tenant_id", "sale_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(UNIT_COST)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    tax_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    returned_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    business_date: Mapped[date] = mapped_column(Date)


class SaleReturn(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        composite_fk("sale_id", "sales"),
        UniqueConstraint("tenant_id", "return_no"),
        tenant_unique(),
        enum_check("status", ("posted", "void")),
    )

    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    return_no: Mapped[str] = mapped_column(Text)
    business_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="posted")
    refund_total: Mapped[Decimal] = mapped_column(MONEY)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class SaleReturnLine(TenantMixin, Base):
    __tablename__ = "sale_return_lines"
    __table_args__ = (
        composite_fk("return_id", "sale_returns"),
        composite_fk("sale_line_id", "sale_lines"),
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        enum_check("disposition", ("restock", "damaged", "expired")),
        Index("ix_sale_return_lines_tenant_return", "tenant_id", "return_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    return_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sale_line_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    refund_amount: Mapped[Decimal] = mapped_column(MONEY)
    disposition: Mapped[str] = mapped_column(Text)
