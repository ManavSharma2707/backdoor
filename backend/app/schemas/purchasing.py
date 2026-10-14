"""Purchase orders and goods receipts (`api-spec.md` section 6)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import (
    MoneyIn,
    MoneyStr,
    PositiveQtyIn,
    PriceIn,
    QtyStr,
    UnitCostIn,
    UnitPriceStr,
)

PoStatus = Literal["draft", "sent", "partially_received", "received", "cancelled", "closed"]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
BatchNo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
    ),
]
MAX_LINES = 200


class POLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity_ordered: PositiveQtyIn
    unit_cost: UnitCostIn | None = Field(
        default=None, description="Defaults to the supplier's current price for the product"
    )


class POCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID
    expected_date: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    notes: Note | None = None
    lines: list[POLineIn] = Field(min_length=1, max_length=MAX_LINES)


class POPatch(BaseModel):
    """Edit a draft. Sending `lines` replaces all of them."""

    model_config = ConfigDict(extra="forbid")

    expected_date: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    notes: Note | None = None
    lines: list[POLineIn] | None = Field(default=None, min_length=1, max_length=MAX_LINES)

    @model_validator(mode="after")
    def _lines_not_null(self) -> Self:
        if "lines" in self.model_fields_set and self.lines is None:
            raise ValueError("lines cannot be empty")
        return self


class POCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Note | None = None


class POLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    quantity_ordered: QtyStr
    quantity_received: QtyStr
    quantity_open: QtyStr
    unit_cost: UnitPriceStr
    pack_size: QtyStr
    line_value: MoneyStr


class TimelineEvent(BaseModel):
    event: Literal["created", "sent", "received", "cancelled", "closed"]
    at: datetime
    detail: str | None = None


class ReceiptSummary(BaseModel):
    id: uuid.UUID
    receipt_no: str
    received_on: date
    created_at: datetime
    invoice_no: str | None
    invoice_total: MoneyStr | None
    is_exception: bool
    lines_total: MoneyStr


class POOut(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    status: PoStatus
    order_date: date
    expected_date: date | None
    is_overdue: bool
    days_late: int
    sent_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    subtotal_estimated: MoneyStr
    source: str
    notes: str | None
    created_at: datetime
    lines: list[POLineOut]
    receipts: list[ReceiptSummary]
    timeline: list[TimelineEvent]


class POListItem(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    status: PoStatus
    order_date: date
    expected_date: date | None
    is_overdue: bool
    days_late: int
    lines: int
    value: MoneyStr
    received_value: MoneyStr = Field(description="Value of what has arrived, at order cost")


# --------------------------------------------------------------------------- receipts


class ReceiptLineBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity_received: PositiveQtyIn
    unit_cost: UnitCostIn
    batch_no: BatchNo | None = Field(
        default=None, description="Required for batch tracked products"
    )
    expiry_date: date | None = Field(
        default=None, description="Required for batch tracked products"
    )
    manufactured_on: date | None = None
    mrp: PriceIn | None = Field(default=None, description="Required for batch tracked products")


class ReceiptLineIn(ReceiptLineBase):
    po_line_id: uuid.UUID


class DirectReceiptLineIn(ReceiptLineBase):
    product_id: uuid.UUID


class ReceiptHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_on: date | None = Field(default=None, description="Defaults to today")
    invoice_no: ShortText | None = None
    invoice_total: MoneyIn | None = None
    is_exception: bool = False
    exception_note: Note | None = None

    @model_validator(mode="after")
    def _exception_needs_a_note(self) -> Self:
        if self.is_exception and not self.exception_note:
            raise ValueError("exception_note is required when is_exception is true")
        return self


class ReceiptCreate(ReceiptHeader):
    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=MAX_LINES)


class DirectReceiptCreate(ReceiptHeader):
    supplier_id: uuid.UUID
    lines: list[DirectReceiptLineIn] = Field(min_length=1, max_length=MAX_LINES)

    @model_validator(mode="after")
    def _must_be_an_exception(self) -> Self:
        if not self.is_exception:
            raise ValueError("A receipt without an order must be marked as an exception")
        return self


class ReceiptWarning(BaseModel):
    code: Literal["PRICE_VARIANCE", "OVER_RECEIPT", "SHORT_RECEIPT", "INVOICE_TOTAL_DIFFERS"]
    message: str
    line_index: int | None = None


class ReceiptLineOut(BaseModel):
    id: uuid.UUID
    po_line_id: uuid.UUID | None
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    batch_id: uuid.UUID | None
    batch_no: str | None
    expiry_date: date | None
    quantity_received: QtyStr
    unit_cost: UnitPriceStr
    mrp: MoneyStr | None
    line_value: MoneyStr


class ReceiptOut(BaseModel):
    id: uuid.UUID
    receipt_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    purchase_order_id: uuid.UUID | None
    po_number: str | None
    po_status: PoStatus | None
    received_on: date
    invoice_no: str | None
    invoice_total: MoneyStr | None
    status: Literal["posted", "void"]
    is_exception: bool
    exception_note: str | None
    created_at: datetime
    lines_total: MoneyStr
    lines: list[ReceiptLineOut]
    warnings: list[ReceiptWarning] = Field(default_factory=list)


class ReceiptListItem(BaseModel):
    id: uuid.UUID
    receipt_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    po_number: str | None
    received_on: date
    invoice_no: str | None
    is_exception: bool
    lines: int
    lines_total: MoneyStr
