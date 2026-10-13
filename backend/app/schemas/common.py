"""Schemas shared by every endpoint."""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer

from app.core.money import money_str, qty_str, round_unit_price


class ErrorDetail(BaseModel):
    field: str = Field(description="Dotted path of the field, for example lines[0].quantity")
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class HealthStatus(BaseModel):
    status: str
    version: str | None = None
    database: str | None = None
    migration: str | None = Field(
        default=None, description="current when the database is at the migration head"
    )


def reject_float(value: Any) -> Any:
    """Money and quantities travel as strings. A JSON float has already lost precision."""
    if isinstance(value, float):
        raise ValueError('send amounts as strings, for example "12.50"')
    return value


def _unit_price_str(value: Decimal) -> str:
    return format(round_unit_price(value), "f")


# Output types: fixed decimals as strings (api-spec.md section 1).
MoneyStr = Annotated[Decimal, PlainSerializer(money_str, return_type=str, when_used="json")]
QtyStr = Annotated[Decimal, PlainSerializer(qty_str, return_type=str, when_used="json")]
UnitPriceStr = Annotated[
    Decimal, PlainSerializer(_unit_price_str, return_type=str, when_used="json")
]

# Input types: bounded decimals that refuse JSON floats.
MoneyIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=0, le=Decimal("999999999999.99"), max_digits=14, decimal_places=2),
]
PriceIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2),
]
UnitCostIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=0, le=Decimal("9999999999.9999"), max_digits=14, decimal_places=4),
]
QtyIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=0, le=Decimal("99999999999.999"), max_digits=14, decimal_places=3),
]
PositiveQtyIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(gt=0, le=Decimal("99999999999.999"), max_digits=14, decimal_places=3),
]
SignedQtyIn = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(
        ge=Decimal("-99999999999.999"),
        le=Decimal("99999999999.999"),
        max_digits=14,
        decimal_places=3,
    ),
]
