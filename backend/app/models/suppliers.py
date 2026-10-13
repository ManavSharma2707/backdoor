"""Suppliers and effective dated supplier product terms."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    MONEY,
    QTY,
    UNIT_COST,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    UpdatedAtMixin,
    composite_fk,
    tenant_unique,
)


class Supplier(IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        tenant_unique(),
        CheckConstraint(
            "delivery_weekdays IS NULL OR delivery_weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[]",
            name="delivery_weekdays_iso",
        ),
    )

    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    default_lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    delivery_weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    min_order_value: Mapped[Decimal | None] = mapped_column(MONEY)
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY)
    accepts_expiry_returns: Mapped[bool] = mapped_column(server_default=text("false"))
    expiry_return_window_days: Mapped[int | None] = mapped_column(SmallInteger)
    return_window_days: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)


class SupplierProductTerm(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "supplier_product_terms"
    __table_args__ = (
        composite_fk("supplier_id", "suppliers"),
        composite_fk("product_id", "products"),
        UniqueConstraint("tenant_id", "supplier_id", "product_id", "effective_from"),
        CheckConstraint("pack_size > 0", name="pack_size_positive"),
        Index(
            "uq_supplier_product_terms_one_primary",
            "tenant_id",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary AND effective_to IS NULL"),
        ),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))
    purchase_price: Mapped[Decimal] = mapped_column(UNIT_COST)
    pack_size: Mapped[Decimal] = mapped_column(QTY, server_default="1")
    moq_units: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
