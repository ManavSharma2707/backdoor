"""Purchase order rules: the state machine, overdue detection, receipt status and price checks.

Pure functions, no database and no clock (`today` is passed in).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Final, Literal

PoAction = Literal["send", "cancel", "close", "receive"]

# status -> action -> status after. Anything missing is not allowed.
TRANSITIONS: Final[dict[str, dict[str, str]]] = {
    "draft": {"send": "sent", "cancel": "cancelled"},
    "sent": {"cancel": "cancelled", "close": "closed", "receive": "partially_received"},
    "partially_received": {"close": "closed", "receive": "partially_received"},
    "received": {"close": "closed"},
    "cancelled": {},
    "closed": {},
}
# Statuses that can still bring goods in. A cancelled or closed order never counts as incoming.
OPEN_STATUSES: Final = frozenset({"sent", "partially_received"})
PRICE_VARIANCE_THRESHOLD: Final = Decimal("0.10")
INVOICE_TOLERANCE: Final = Decimal("1.00")


def next_status(status: str, action: PoAction) -> str | None:
    """The status after `action`, or None when the action is not allowed from `status`."""
    return TRANSITIONS.get(status, {}).get(action)


def can_edit(status: str) -> bool:
    return status == "draft"


def open_quantity(ordered: Decimal, received: Decimal) -> Decimal:
    """What is still to come on a line. Never negative, even after an over receipt."""
    return max(ordered - received, Decimal(0))


def status_after_receipt(lines: Sequence[tuple[Decimal, Decimal]]) -> str:
    """`received` when every line has arrived in full, else `partially_received`.

    `lines` holds (ordered, received) pairs after the receipt was applied.
    """
    if lines and all(received >= ordered for ordered, received in lines):
        return "received"
    return "partially_received"


def days_late(status: str, expected_date: date | None, today: date) -> int:
    """Days past the expected date for an order that can still bring goods. Else 0."""
    if status not in OPEN_STATUSES or expected_date is None or expected_date >= today:
        return 0
    return (today - expected_date).days


def is_overdue(status: str, expected_date: date | None, today: date) -> bool:
    return days_late(status, expected_date, today) > 0


def price_variance(order_cost: Decimal, receipt_cost: Decimal) -> Decimal | None:
    """Relative change from the ordered cost when it is more than 10 percent, else None.

    Positive means the supplier charged more. An order cost of zero has no sensible ratio.
    """
    if order_cost <= 0:
        return None
    change = (receipt_cost - order_cost) / order_cost
    return change if abs(change) > PRICE_VARIANCE_THRESHOLD else None


def invoice_differs(invoice_total: Decimal | None, lines_total: Decimal) -> bool:
    """True when the invoice total is more than a rupee away from the sum of the lines."""
    return invoice_total is not None and abs(invoice_total - lines_total) > INVOICE_TOLERANCE
