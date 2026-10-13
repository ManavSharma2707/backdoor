"""Purchase orders, goods receipts and their lines."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    MONEY,
    PRICE,
    QTY,
    TZ,
    UNIT_COST,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    UpdatedAtMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)

PO_STATUSES = ("draft", "sent", "partially_received", "received", "cancelled", "closed")


class PurchaseOrder(IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        composite_fk("supplier_id", "suppliers"),
        UniqueConstraint("tenant_id", "po_number"),
        tenant_unique(),
        enum_check("status", PO_STATUSES),
        enum_check("source", ("manual", "recommendation", "seed")),
        Index("ix_purchase_orders_tenant_status_expected", "tenant_id", "status", "expected_date"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    po_number: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    cancelled_at: Mapped[datetime | None] = mapped_column(TZ)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    subtotal_estimated: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    source: Mapped[str] = mapped_column(Text, server_default="manual")
    # Soft reference to the plan that produced this order. Plans live in a later migration.
    recommendation_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class PurchaseOrderLine(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        composite_fk("po_id", "purchase_orders"),
        composite_fk("product_id", "products"),
        UniqueConstraint("tenant_id", "po_id", "product_id"),
        tenant_unique(),
        CheckConstraint("quantity_ordered > 0", name="quantity_positive"),
    )

    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quantity_ordered: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(UNIT_COST)
    pack_size: Mapped[Decimal] = mapped_column(QTY)
    quantity_received: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    recommendation_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class GoodsReceipt(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        composite_fk("supplier_id", "suppliers"),
        composite_fk("purchase_order_id", "purchase_orders"),
        UniqueConstraint("tenant_id", "receipt_no"),
        tenant_unique(),
        enum_check("status", ("posted", "void")),
        CheckConstraint(
            "NOT is_exception OR exception_note IS NOT NULL", name="exception_needs_note"
        ),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    receipt_no: Mapped[str] = mapped_column(Text)
    received_on: Mapped[date] = mapped_column(Date)
    invoice_no: Mapped[str | None] = mapped_column(Text)
    invoice_total: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(Text, server_default="posted")
    is_exception: Mapped[bool] = mapped_column(server_default=text("false"))
    exception_note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ReceiptLine(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "receipt_lines"
    __table_args__ = (
        composite_fk("receipt_id", "goods_receipts"),
        composite_fk("po_line_id", "purchase_order_lines"),
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        CheckConstraint("quantity_received > 0", name="quantity_positive"),
        Index("ix_receipt_lines_tenant_receipt", "tenant_id", "receipt_id"),
    )

    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quantity_received: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal] = mapped_column(UNIT_COST)
    mrp: Mapped[Decimal | None] = mapped_column(PRICE)
