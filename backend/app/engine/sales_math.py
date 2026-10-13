"""Bill arithmetic: line totals, tax contained in the price, discount splits and refunds.

Prices in India include GST, so tax is not added to a line, it is the part of the line total that
is tax. All results are whole paise, and the parts always add up to the whole. Pure functions.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.core.money import HUNDRED, PAISA, round_money

__all__ = [
    "gross_amount",
    "refund_for",
    "split_discount",
    "tax_contained",
]


def gross_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Quantity times unit price, rounded to paise, before any discount."""
    return round_money(quantity * unit_price)


def tax_contained(line_total: Decimal, rate_pct: Decimal) -> Decimal:
    """The GST inside a price that already includes it: total * rate / (100 + rate)."""
    if rate_pct == 0:
        return Decimal("0.00")
    return round_money(line_total * rate_pct / (HUNDRED + rate_pct))


def split_discount(discount: Decimal, grosses: Sequence[Decimal]) -> list[Decimal]:
    """Share a bill line discount across the parts a line was split into.

    Shares follow each part's gross amount, in whole paise, with the leftover paise going to the
    parts with the biggest fractional remainders. The shares add up to `discount` and no share
    is more than its part's gross, as long as `discount` is not more than the total gross.
    """
    total_paise = int((round_money(discount) / PAISA).to_integral_value())
    gross_paise = [int((round_money(g) / PAISA).to_integral_value()) for g in grosses]
    gross_sum = sum(gross_paise)
    if total_paise < 0 or total_paise > gross_sum:
        raise ValueError("Discount must be between zero and the gross amount")
    if total_paise == 0:
        return [Decimal("0.00")] * len(grosses)

    shares = [total_paise * g // gross_sum for g in gross_paise]
    remainders = [total_paise * g % gross_sum for g in gross_paise]
    leftover = total_paise - sum(shares)
    by_remainder = sorted(range(len(grosses)), key=lambda i: (-remainders[i], i))
    for index in by_remainder[:leftover]:
        shares[index] += 1
    return [Decimal(s) * PAISA for s in shares]


def refund_for(
    line_total: Decimal, quantity: Decimal, returned_before: Decimal, returning: Decimal
) -> Decimal:
    """Money back for returning `returning` more units of a bill line.

    Computed as the refund for everything returned so far minus the refund already given, so
    several part returns add up to exactly the line total when the whole line comes back.
    """
    if quantity <= 0 or returning <= 0 or returned_before < 0:
        raise ValueError("Quantities must be positive")
    if returned_before + returning > quantity:
        raise ValueError("Cannot return more than was sold")

    def cumulative(units: Decimal) -> Decimal:
        return (line_total * units / quantity).quantize(PAISA, rounding=ROUND_HALF_UP)

    return cumulative(returned_before + returning) - cumulative(returned_before)
