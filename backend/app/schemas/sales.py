"""Bills, returns and sales summaries (`api-spec.md` section 5)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import (
    MoneyIn,
    MoneyStr,
    PositiveQtyIn,
    QtyStr,
    UnitCostIn,
    UnitPriceStr,
)

PaymentMode = Literal["cash", "upi", "card", "credit"]
SaleStatus = Literal["completed", "void"]
Disposition = Literal["restock", "damaged", "expired"]
BillNo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
    ),
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
MAX_LINES = 100


class SaleLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: PositiveQtyIn
    unit_price: UnitCostIn | None = Field(
        default=None, description="Defaults to the product's selling price. Cannot exceed the MRP"
    )
    discount_amount: MoneyIn = Field(default=Decimal(0), description="Total for the whole line")
    batch_id: uuid.UUID | None = Field(
        default=None, description="Only to override the first-expired-first-out choice"
    )


class SaleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sold_at: AwareDatetime | None = Field(default=None, description="Defaults to now")
    payment_mode: PaymentMode
    lines: list[SaleLineIn] = Field(min_length=1, max_length=MAX_LINES)
    bill_no: BillNo | None = Field(default=None, description="Generated when left out")


class SaleLineOut(BaseModel):
    id: int
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    batch_id: uuid.UUID | None
    batch_no: str | None
    expiry_date: date | None
    quantity: QtyStr
    unit_price: UnitPriceStr
    discount_amount: MoneyStr
    tax_rate_pct: Decimal
    tax_amount: MoneyStr = Field(description="GST contained in the line total")
    line_total: MoneyStr
    returned_qty: QtyStr


class ReturnLineOut(BaseModel):
    id: int
    sale_line_id: int
    product_id: uuid.UUID
    product_name: str
    batch_id: uuid.UUID | None
    quantity: QtyStr
    refund_amount: MoneyStr
    disposition: Disposition


class ReturnOut(BaseModel):
    id: uuid.UUID
    sale_id: uuid.UUID
    bill_no: str
    return_no: str
    business_date: date
    reason: str
    status: Literal["posted", "void"]
    refund_total: MoneyStr
    created_at: datetime
    lines: list[ReturnLineOut]


class SaleWarning(BaseModel):
    code: Literal["POSSIBLE_DUPLICATE"]
    message: str
    sale_id: uuid.UUID | None = None


class SaleOut(BaseModel):
    id: uuid.UUID
    bill_no: str
    business_date: date
    sold_at: datetime
    payment_mode: PaymentMode
    status: SaleStatus
    subtotal: MoneyStr
    discount_total: MoneyStr
    tax_total: MoneyStr
    total: MoneyStr
    void_reason: str | None
    voided_at: datetime | None
    source: str
    created_at: datetime
    lines: list[SaleLineOut]
    returns: list[ReturnOut] = Field(default_factory=list)
    warnings: list[SaleWarning] = Field(default_factory=list)


class SaleListItem(BaseModel):
    id: uuid.UUID
    bill_no: str
    business_date: date
    sold_at: datetime
    payment_mode: PaymentMode
    status: SaleStatus
    items: int = Field(description="Number of lines on the bill")
    total: MoneyStr
    returned_total: MoneyStr


class VoidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ReturnLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sale_line_id: int = Field(gt=0)
    quantity: PositiveQtyIn
    disposition: Disposition


class ReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=MAX_LINES)


class SalesPoint(BaseModel):
    period: date = Field(description="The day, or the Monday of the week")
    bills: int
    sales: MoneyStr = Field(description="Completed bills")
    returns: MoneyStr = Field(description="Refunds on returns posted in the period")
    discounts: MoneyStr


class SalesSummary(BaseModel):
    group: Literal["day", "week"]
    bills: int
    sales: MoneyStr
    returns: MoneyStr
    discounts: MoneyStr
    series: list[SalesPoint]
