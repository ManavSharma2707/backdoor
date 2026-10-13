"""Decimal helpers. Money and quantities are never floats."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISA = Decimal("0.01")
UNIT_PRICE_STEP = Decimal("0.0001")
QTY_STEP = Decimal("0.001")
HUNDRED = Decimal(100)


def to_decimal(value: Decimal | int | str | float) -> Decimal:
    """Convert to Decimal without binary float noise. Rejects NaN and infinity."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        result = Decimal(repr(value))
    else:
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Not a decimal number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Not a finite number: {value!r}")
    return result


def _quantize(value: Decimal | int | str | float, step: Decimal) -> Decimal:
    return to_decimal(value).quantize(step, rounding=ROUND_HALF_UP)


def round_money(value: Decimal | int | str | float) -> Decimal:
    """Round to whole paise (2 places), half up."""
    return _quantize(value, PAISA)


def round_unit_price(value: Decimal | int | str | float) -> Decimal:
    """Round to 4 places, the precision of unit prices and costs."""
    return _quantize(value, UNIT_PRICE_STEP)


def round_qty(value: Decimal | int | str | float) -> Decimal:
    """Round to 3 places, the precision of quantities."""
    return _quantize(value, QTY_STEP)


def to_paise(value: Decimal | int | str | float) -> int:
    """Rupees to whole paise as an integer."""
    return int(round_money(value) * HUNDRED)


def from_paise(paise: int) -> Decimal:
    return (Decimal(paise) / HUNDRED).quantize(PAISA, rounding=ROUND_HALF_UP)


def line_total(quantity: Decimal, unit_price: Decimal, discount: Decimal = Decimal(0)) -> Decimal:
    """Quantity times unit price minus discount, rounded to paise."""
    return round_money(quantity * unit_price - discount)


def money_str(value: Decimal | int | str | float) -> str:
    """JSON representation: a string with exactly two decimals."""
    return format(round_money(value), "f")


def qty_str(value: Decimal | int | str | float) -> str:
    """JSON representation: a string with exactly three decimals."""
    return format(round_qty(value), "f")
