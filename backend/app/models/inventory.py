"""Batches, the movement ledger, balances, counts, adjustments and stockout intervals."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
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

MOVEMENT_TYPES = (
    "opening",
    "receipt",
    "sale",
    "void_reversal",
    "return_in",
    "damage",
    "expiry_writeoff",
    "supplier_return",
    "adjustment",
    "count_correction",
)
MOVEMENT_SOURCES = (
    "sale",
    "sale_return",
    "receipt",
    "adjustment",
    "stock_count",
    "opening",
    "void",
)
ADJUSTMENT_REASONS = (
    "damage",
    "expiry_writeoff",
    "theft_loss",
    "found",
    "correction",
    "supplier_return",
    "other",
)


class ProductBatch(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "product_batches"
    __table_args__ = (
        composite_fk("product_id", "products"),
        UniqueConstraint("tenant_id", "product_id", "batch_no"),
        tenant_unique(),
        enum_check("status", ("active", "quarantined", "expired", "closed")),
        Index("ix_product_batches_tenant_expiry", "tenant_id", "expiry_date"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_no: Mapped[str] = mapped_column(Text)
    expiry_date: Mapped[date] = mapped_column(Date)
    manufactured_on: Mapped[date | None] = mapped_column(Date)
    mrp: Mapped[Decimal | None] = mapped_column(PRICE)
    unit_cost: Mapped[Decimal] = mapped_column(UNIT_COST)
    received_on: Mapped[date] = mapped_column(Date)
    initial_qty: Mapped[Decimal] = mapped_column(QTY)
    status: Mapped[str] = mapped_column(Text, server_default="active")


class InventoryMovement(TenantMixin, CreatedAtMixin, Base):
    """The ledger. Rows are never edited, corrections are new rows."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        composite_fk("reverses_movement_id", "inventory_movements"),
        tenant_unique(),
        CheckConstraint("quantity_delta <> 0", name="delta_not_zero"),
        enum_check("movement_type", MOVEMENT_TYPES),
        enum_check("source_type", MOVEMENT_SOURCES),
        Index(
            "ix_inventory_movements_tenant_product_date", "tenant_id", "product_id", "business_date"
        ),
        Index("ix_inventory_movements_tenant_source", "tenant_id", "source_type", "source_id"),
        Index("ix_inventory_movements_tenant_batch", "tenant_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    movement_type: Mapped[str] = mapped_column(Text)
    quantity_delta: Mapped[Decimal] = mapped_column(QTY)
    unit_cost: Mapped[Decimal | None] = mapped_column(UNIT_COST)
    occurred_at: Mapped[datetime] = mapped_column(TZ)
    business_date: Mapped[date] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    reverses_movement_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class StockBalance(IdMixin, TenantMixin, UpdatedAtMixin, Base):
    """Transactional cache of the ledger per product and batch."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        UniqueConstraint("tenant_id", "product_id", "batch_id", postgresql_nulls_not_distinct=True),
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
        Index("ix_stock_balances_tenant_product", "tenant_id", "product_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    on_hand: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    reserved_qty: Mapped[Decimal] = mapped_column(QTY, server_default="0")
    avg_unit_cost: Mapped[Decimal] = mapped_column(UNIT_COST, server_default="0")
    last_movement_at: Mapped[datetime | None] = mapped_column(TZ)


class StockCount(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "stock_counts"
    __table_args__ = (tenant_unique(), enum_check("status", ("draft", "posted", "void")))

    count_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(TZ)


class StockCountLine(IdMixin, TenantMixin, Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (
        composite_fk("count_id", "stock_counts"),
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        UniqueConstraint(
            "tenant_id", "count_id", "product_id", "batch_id", postgresql_nulls_not_distinct=True
        ),
    )

    count_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    system_qty: Mapped[Decimal] = mapped_column(QTY)
    counted_qty: Mapped[Decimal | None] = mapped_column(QTY)
    variance: Mapped[Decimal | None] = mapped_column(
        QTY, Computed("counted_qty - system_qty", persisted=True)
    )


class StockAdjustment(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "stock_adjustments"
    __table_args__ = (
        composite_fk("product_id", "products"),
        composite_fk("batch_id", "product_batches"),
        composite_fk("movement_id", "inventory_movements"),
        CheckConstraint("quantity_delta <> 0", name="delta_not_zero"),
        enum_check("reason_code", ADJUSTMENT_REASONS),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quantity_delta: Mapped[Decimal] = mapped_column(QTY)
    reason_code: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    business_date: Mapped[date] = mapped_column(Date)
    movement_id: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class StockoutInterval(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "stockout_intervals"
    __table_args__ = (
        composite_fk("product_id", "products"),
        UniqueConstraint("tenant_id", "product_id", "start_date", "source"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
        enum_check("source", ("recorded", "inferred")),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
