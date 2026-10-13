"""Categories, products, prices, equivalents and tax rates."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.common import MoneyStr, PriceIn, QtyIn, QtyStr

BaseUnit = Literal[
    "pcs", "pack", "strip", "bottle", "tube", "sachet", "box", "kg", "litre", "vial", "tin"
]
ScheduleClass = Literal["H", "H1", "X"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Sku = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/#-]*$",
    ),
]
Barcode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=4, max_length=32, pattern=r"^[A-Za-z0-9-]+$"
    ),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
SHELF_LIFE_MAX_DAYS = 3650
MEDICINE_FIELDS = ("generic_name", "strength", "dosage_form", "manufacturer", "schedule_class")


# --------------------------------------------------------------------------- categories


class CategoryCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    parent_id: uuid.UUID | None = None
    position: int = Field(default=0, ge=0, le=999)


class CategoryPatch(BaseModel):
    """Send `parent_id: null` to move a category to the top level."""

    model_config = ConfigDict(extra="forbid")

    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None
    ) = None
    parent_id: uuid.UUID | None = None
    position: int | None = Field(default=None, ge=0, le=999)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> Self:
        for name in ("name", "position", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    position: int
    is_active: bool
    product_count: int = 0


# --------------------------------------------------------------------------- products


class ProductFields(BaseModel):
    """Fields shared by create and the full read model."""

    model_config = ConfigDict(extra="forbid")

    barcode: Barcode | None = None
    brand: ShortText | None = None
    pack_label: ShortText | None = None
    is_batch_tracked: bool = False
    shelf_life_days: int | None = Field(default=None, ge=1, le=SHELF_LIFE_MAX_DAYS)
    schedule_class: ScheduleClass | None = Field(
        default=None, description="Flag for your records only. It never changes any calculation."
    )
    generic_name: ShortText | None = None
    strength: ShortText | None = None
    dosage_form: ShortText | None = None
    manufacturer: ShortText | None = None
    min_stock_qty: QtyIn = Decimal("0")
    is_seasonal: bool = False
    launched_on: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    notes: NoteText | None = None


class ProductCreate(ProductFields):
    sku: Sku
    name: Name
    category_id: uuid.UUID
    base_unit: BaseUnit
    tax_rate_id: uuid.UUID
    mrp: PriceIn
    selling_price: PriceIn

    @field_validator("selling_price")
    @classmethod
    def _selling_price_within_mrp(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        mrp = info.data.get("mrp")
        if mrp is not None and value > mrp:
            raise ValueError("cannot be above the MRP")
        return value


class ProductPatch(BaseModel):
    """Only the fields sent change. A new MRP or selling price adds a price history row."""

    model_config = ConfigDict(extra="forbid")

    sku: Sku | None = None
    name: Name | None = None
    category_id: uuid.UUID | None = None
    base_unit: BaseUnit | None = None
    tax_rate_id: uuid.UUID | None = None
    mrp: PriceIn | None = None
    selling_price: PriceIn | None = None
    price_change_reason: ShortText | None = None
    barcode: Barcode | None = None
    brand: ShortText | None = None
    pack_label: ShortText | None = None
    is_batch_tracked: bool | None = None
    shelf_life_days: int | None = Field(default=None, ge=1, le=SHELF_LIFE_MAX_DAYS)
    schedule_class: ScheduleClass | None = None
    generic_name: ShortText | None = None
    strength: ShortText | None = None
    dosage_form: ShortText | None = None
    manufacturer: ShortText | None = None
    min_stock_qty: QtyIn | None = None
    is_seasonal: bool | None = None
    launched_on: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    notes: NoteText | None = None

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> Self:
        required = (
            "sku",
            "name",
            "category_id",
            "base_unit",
            "tax_rate_id",
            "mrp",
            "selling_price",
            "is_batch_tracked",
            "min_stock_qty",
            "is_seasonal",
        )
        for name in required:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    barcode: str | None
    name: str
    brand: str | None
    category_id: uuid.UUID
    category_name: str
    base_unit: str
    pack_label: str | None
    tax_rate_id: uuid.UUID
    tax_rate_code: str
    tax_rate_pct: Decimal
    mrp: MoneyStr
    selling_price: MoneyStr
    is_batch_tracked: bool
    shelf_life_days: int | None
    schedule_class: str | None
    generic_name: str | None
    strength: str | None
    dosage_form: str | None
    manufacturer: str | None
    min_stock_qty: QtyStr
    is_seasonal: bool
    launched_on: date | None
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    on_hand: QtyStr
    primary_supplier_id: uuid.UUID | None = None
    primary_supplier_name: str | None = None
    days_of_cover: Decimal | None = Field(
        default=None, description="Filled from the Monday plan once one exists"
    )
    plan_status: str | None = Field(
        default=None, description="Buy, Watch or OK from the current plan, once one exists"
    )


class PriceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mrp: MoneyStr
    selling_price: MoneyStr
    effective_from: date
    effective_to: date | None
    reason: str | None


class EquivalentCreate(BaseModel):
    equivalent_product_id: uuid.UUID
    note: NoteText | None = Field(
        default=None, description="Your own words. Do not put dosing or clinical advice here."
    )


class EquivalentOut(BaseModel):
    id: uuid.UUID
    equivalent_product_id: uuid.UUID
    equivalent_sku: str
    equivalent_name: str
    equivalent_on_hand: QtyStr
    note: str | None
    created_at: datetime


class TaxRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    rate_pct: Decimal
    label: str
    effective_from: date
    effective_to: date | None
    notes: str | None


ProductStatus = Literal["active", "inactive", "all"]
