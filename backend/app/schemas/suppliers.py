"""Suppliers and effective dated supplier product terms."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.engine.lead_time import MAX_LEAD_TIME_DAYS, LeadTimeSource
from app.schemas.common import (
    MoneyIn,
    MoneyStr,
    PositiveQtyIn,
    QtyIn,
    QtyStr,
    UnitCostIn,
    UnitPriceStr,
)

Code = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Phone = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=5, max_length=20, pattern=r"^[0-9+()\- ]+$"
    ),
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Weekdays = list[Annotated[int, Field(ge=1, le=7)]]


class SupplierFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_name: Name | None = None
    phone: Phone | None = None
    email: EmailStr | None = Field(default=None, max_length=254)
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    default_lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)
    delivery_weekdays: Weekdays | None = Field(
        default=None, max_length=7, description="ISO weekdays, Monday is 1 and Sunday is 7"
    )
    min_order_value: MoneyIn | None = None
    credit_limit: MoneyIn | None = None
    accepts_expiry_returns: bool = False
    expiry_return_window_days: int | None = Field(default=None, ge=0, le=730)
    return_window_days: int | None = Field(default=None, ge=0, le=730)
    notes: Note | None = None

    @field_validator("delivery_weekdays")
    @classmethod
    def _unique_sorted(cls, value: Weekdays | None) -> Weekdays | None:
        if value is None:
            return None
        return sorted(set(value)) or None


class SupplierCreate(SupplierFields):
    code: Code
    name: Name


class SupplierPatch(BaseModel):
    """Only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    code: Code | None = None
    name: Name | None = None
    contact_name: Name | None = None
    phone: Phone | None = None
    email: EmailStr | None = Field(default=None, max_length=254)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    default_lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)
    delivery_weekdays: Weekdays | None = Field(default=None, max_length=7)
    min_order_value: MoneyIn | None = None
    credit_limit: MoneyIn | None = None
    accepts_expiry_returns: bool | None = None
    expiry_return_window_days: int | None = Field(default=None, ge=0, le=730)
    return_window_days: int | None = Field(default=None, ge=0, le=730)
    is_active: bool | None = None
    notes: Note | None = None

    @field_validator("delivery_weekdays")
    @classmethod
    def _unique_sorted(cls, value: Weekdays | None) -> Weekdays | None:
        if value is None:
            return None
        return sorted(set(value)) or None

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> Self:
        for name in ("code", "name", "payment_terms_days", "accepts_expiry_returns", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    payment_terms_days: int
    default_lead_time_days: int | None
    delivery_weekdays: list[int] | None
    min_order_value: MoneyStr | None
    credit_limit: MoneyStr | None
    accepts_expiry_returns: bool
    expiry_return_window_days: int | None
    return_window_days: int | None
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    current_terms: int = Field(default=0, description="Products with a term in force today")


class TermCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    purchase_price: UnitCostIn = Field(gt=0)
    pack_size: PositiveQtyIn = Field(default=Decimal(1))
    moq_units: QtyIn = Field(default=Decimal(0))
    lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)
    is_primary: bool = False
    effective_from: date | None = Field(
        default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1), description="Defaults to today"
    )
    effective_to: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot be before effective_from")
        return self


class TermPatch(BaseModel):
    """Past prices are history, so price and start date change only on a term that has not
    started yet. Everything else can be corrected, and `effective_to` ends a term."""

    model_config = ConfigDict(extra="forbid")

    purchase_price: UnitCostIn | None = Field(default=None, gt=0)
    pack_size: PositiveQtyIn | None = None
    moq_units: QtyIn | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)
    is_primary: bool | None = None
    effective_from: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))
    effective_to: date | None = Field(default=None, ge=date(2000, 1, 1), le=date(2100, 1, 1))

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> Self:
        for name in ("purchase_price", "pack_size", "moq_units", "is_primary", "effective_from"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class TermOut(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    is_primary: bool
    purchase_price: UnitPriceStr
    pack_size: QtyStr
    moq_units: QtyStr
    lead_time_days: int | None
    lead_time_source: LeadTimeSource
    resolved_lead_time_days: int = Field(
        description="Term, else supplier default, else business default"
    )
    effective_from: date
    effective_to: date | None
    in_force: bool = Field(description="True when today falls inside the range")
    created_at: datetime
