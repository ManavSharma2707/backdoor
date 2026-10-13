"""Pure rules of the stock ledger: movement signs, weighted average cost and FEFO allocation.

No database, no clock: callers pass `on` (the business date) in. The transactional class that
applies these rules is `app/services/ledger.py`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

ZERO: Final = Decimal(0)
COST_STEP: Final = Decimal("0.0001")
QTY_STEP: Final = Decimal("0.001")

# +1 the delta must be positive, -1 negative, 0 either sign (never zero).
SIGN_RULES: Final[dict[str, int]] = {
    "opening": 1,
    "receipt": 1,
    "void_reversal": 1,
    "return_in": 1,
    "sale": -1,
    "damage": -1,
    "expiry_writeoff": -1,
    "supplier_return": -1,
    "adjustment": 0,
    "count_correction": 0,
}
# Only these add purchased stock at a known cost, so only these move the average cost.
COST_SETTING_TYPES: Final = frozenset({"receipt", "opening"})


class LedgerRuleError(ValueError):
    """A movement that breaks a ledger rule (wrong sign, zero, unknown type)."""


def check_movement(movement_type: str, quantity_delta: Decimal) -> None:
    """Raise `LedgerRuleError` unless the type is known and the sign matches (`database.md` 5)."""
    rule = SIGN_RULES.get(movement_type)
    if rule is None:
        raise LedgerRuleError(f"Unknown movement type {movement_type!r}")
    if quantity_delta == 0:
        raise LedgerRuleError("A movement cannot be zero")
    if rule > 0 and quantity_delta < 0:
        raise LedgerRuleError(f"{movement_type} must add stock")
    if rule < 0 and quantity_delta > 0:
        raise LedgerRuleError(f"{movement_type} must remove stock")


def weighted_average_cost(
    on_hand: Decimal, average_cost: Decimal, added_qty: Decimal, added_cost: Decimal
) -> Decimal:
    """Average cost after adding `added_qty` at `added_cost` to `on_hand` at `average_cost`.

    Empty stock takes the new cost outright. Rounded to the 4 places of a unit cost.
    """
    if added_qty <= 0:
        raise LedgerRuleError("Weighted average needs a positive quantity")
    if on_hand <= 0:
        return added_cost.quantize(COST_STEP, rounding=ROUND_HALF_UP)
    total = on_hand * average_cost + added_qty * added_cost
    return (total / (on_hand + added_qty)).quantize(COST_STEP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BatchStock:
    """One batch as seen by the allocator."""

    batch_id: uuid.UUID
    batch_no: str
    expiry_date: date
    on_hand: Decimal
    status: str = "active"


def is_sellable(batch: BatchStock, on: date) -> bool:
    """Active, not expired (the expiry date is the first day it cannot be sold) and in stock."""
    return batch.status == "active" and batch.expiry_date > on and batch.on_hand > 0


def fefo_order(batches: Sequence[BatchStock]) -> list[BatchStock]:
    """First expired, first out. Ties go to the batch number so the order is deterministic."""
    return sorted(batches, key=lambda b: (b.expiry_date, b.batch_no, str(b.batch_id)))


@dataclass(frozen=True)
class Allocation:
    parts: tuple[tuple[uuid.UUID, Decimal], ...]
    shortfall: Decimal

    @property
    def complete(self) -> bool:
        return self.shortfall == 0


def allocate_fefo(batches: Sequence[BatchStock], quantity: Decimal, on: date) -> Allocation:
    """Take `quantity` from the sellable batches, earliest expiry first.

    Never takes from a later batch while an earlier sellable one has stock. Whatever cannot be
    covered is the shortfall.
    """
    if quantity <= 0:
        raise LedgerRuleError("Quantity must be more than zero")
    remaining = quantity
    parts: list[tuple[uuid.UUID, Decimal]] = []
    for batch in fefo_order([b for b in batches if is_sellable(b, on)]):
        if remaining == 0:
            break
        take = min(batch.on_hand, remaining)
        parts.append((batch.batch_id, take))
        remaining -= take
    return Allocation(parts=tuple(parts), shortfall=remaining)


def batch_problem(batch: BatchStock, quantity: Decimal, on: date) -> str | None:
    """Why a batch chosen by hand cannot supply `quantity`: `expired`, `unavailable`, `short`."""
    if batch.expiry_date <= on:
        return "expired"
    if batch.status != "active":
        return "unavailable"
    if batch.on_hand < quantity:
        return "short"
    return None
