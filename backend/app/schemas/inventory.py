"""Stock levels, batches, movements, adjustments, counts, stockouts and reconciliation."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import MoneyStr, PositiveQtyIn, QtyIn, QtyStr, SignedQtyIn, UnitPriceStr

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ReasonCode = Literal[
    "damage", "expiry_writeoff", "theft_loss", "found", "correction", "supplier_return", "other"
]
StockStatus = Literal["out", "low", "ok", "expired"]
MovementType = Literal[
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
]
MAX_LINES = 500


class StockRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    category_id: uuid.UUID
    category_name: str
    base_unit: str
    is_batch_tracked: bool
    is_active: bool
    on_hand: QtyStr
    sellable: QtyStr = Field(description="On hand minus expired, held and reserved stock")
    reserved: QtyStr
    incoming: QtyStr = Field(description="Open quantity on sent orders that are not overdue")
    incoming_overdue: QtyStr = Field(description="Open quantity on overdue orders, not counted on")
    min_stock_qty: QtyStr
    value: MoneyStr = Field(description="On hand at weighted average cost")
    status: StockStatus
    risk_level: str | None = Field(description="From the latest plan, null before the first plan")
    days_of_cover: Decimal | None = None
    last_count_date: date | None


class BatchRow(BaseModel):
    batch_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    batch_no: str
    expiry_date: date
    days_to_expiry: int = Field(description="Negative when already expired")
    on_hand: QtyStr
    unit_cost: UnitPriceStr
    value: MoneyStr
    mrp: MoneyStr | None
    status: Literal["active", "quarantined", "expired", "closed"]
    is_expired: bool
    sell_first: bool = Field(description="The earliest sellable batch of its product")


class MovementRow(BaseModel):
    id: int
    occurred_at: datetime
    business_date: date
    product_id: uuid.UUID
    sku: str
    name: str
    batch_id: uuid.UUID | None
    batch_no: str | None
    movement_type: MovementType
    quantity_delta: QtyStr
    unit_cost: UnitPriceStr | None
    reason_code: str | None
    note: str | None
    source_type: str
    source_id: str
    reverses_movement_id: int | None
    created_by_name: str | None


class ProductStockOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    is_batch_tracked: bool
    on_hand: QtyStr
    sellable: QtyStr
    value: MoneyStr
    batches: list[BatchRow]


# --------------------------------------------------------------------------- adjustments


class AdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    batch_id: uuid.UUID | None = Field(
        default=None, description="Required for batch tracked products"
    )
    quantity_delta: SignedQtyIn = Field(description="Plus adds stock, minus removes it")
    reason_code: ReasonCode
    note: Note | None = None

    @model_validator(mode="after")
    def _checks(self) -> Self:
        if self.quantity_delta == 0:
            raise ValueError("quantity_delta cannot be zero")
        if self.reason_code == "other" and not self.note:
            raise ValueError("note is required when the reason is other")
        removes = {"damage", "expiry_writeoff", "theft_loss", "supplier_return"}
        if self.reason_code in removes and self.quantity_delta > 0:
            raise ValueError(f"{self.reason_code} removes stock, so quantity_delta must be minus")
        if self.reason_code == "found" and self.quantity_delta < 0:
            raise ValueError("found adds stock, so quantity_delta must be plus")
        return self


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    batch_id: uuid.UUID | None
    batch_no: str | None
    quantity_delta: QtyStr
    reason_code: ReasonCode
    note: str | None
    business_date: date
    movement_id: int
    on_hand_after: QtyStr = Field(description="Stock of that product (and batch) after the change")
    created_at: datetime


class WriteOffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["expired", "damaged"]
    note: Note | None = None


class SupplierReturnLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    batch_id: uuid.UUID | None = None
    quantity: PositiveQtyIn


class SupplierReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note
    credit_note_no: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None
    ) = None
    lines: list[SupplierReturnLine] = Field(min_length=1, max_length=MAX_LINES)


class SupplierReturnOut(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    adjustments: list[AdjustmentOut]


# --------------------------------------------------------------------------- counts


class CountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count_date: date | None = Field(default=None, description="Defaults to today")
    scope: Literal["all", "category", "products"] = "all"
    category_id: uuid.UUID | None = None
    product_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_LINES)
    note: Note | None = None

    @model_validator(mode="after")
    def _scope_matches(self) -> Self:
        if self.scope == "category" and self.category_id is None:
            raise ValueError("category_id is required for a category count")
        if self.scope == "products" and not self.product_ids:
            raise ValueError("product_ids is required for a count of chosen products")
        return self


class CountLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    batch_id: uuid.UUID | None
    batch_no: str | None
    expiry_date: date | None
    system_qty: QtyStr
    counted_qty: QtyStr | None
    variance: QtyStr | None


class CountOut(BaseModel):
    id: uuid.UUID
    count_date: date
    status: Literal["draft", "posted", "void"]
    note: str | None
    posted_at: datetime | None
    created_at: datetime
    lines: list[CountLineOut]
    counted_lines: int
    variance_lines: int
    variance_value: MoneyStr = Field(description="Value of the differences at average cost")


class CountListItem(BaseModel):
    id: uuid.UUID
    count_date: date
    status: Literal["draft", "posted", "void"]
    note: str | None
    posted_at: datetime | None
    created_at: datetime
    lines: int
    counted_lines: int


class CountLineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    counted_qty: QtyIn | None = Field(description="Null clears the entry")


class CountLinesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[CountLineEntry] = Field(min_length=1, max_length=MAX_LINES)


# --------------------------------------------------------------------------- stockouts


class StockoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    start_date: date = Field(ge=date(2000, 1, 1), le=date(2100, 1, 1))
    end_date: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    note: Note | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class StockoutPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    note: Note | None = None


class StockoutOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    start_date: date
    end_date: date | None
    source: Literal["recorded", "inferred"]
    note: str | None
    days: int | None = Field(description="Length in days, null while still open")
    created_at: datetime


# --------------------------------------------------------------------------- reconciliation


class MismatchOut(BaseModel):
    code: str
    entity_type: str
    entity_id: str
    detail: dict[str, str]


class ReconcileOut(BaseModel):
    ok: bool
    checked_at: datetime
    mismatches: list[MismatchOut]
