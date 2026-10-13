"""Lead time resolution and delivery dates. Pure functions: no database, no clock.

Order of precedence (`engine-spec.md` section 9): the supplier term for the product, then the
supplier default, then the business default. Only the last one is an assumption, and callers
show it as one.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

LeadTimeSource = Literal["product_term", "supplier_default", "business_default"]
DEFAULT_LEAD_TIME_DAYS = 3
MAX_LEAD_TIME_DAYS = 60


@dataclass(frozen=True)
class LeadTime:
    days: int
    source: LeadTimeSource

    @property
    def is_assumed(self) -> bool:
        """The business default is a guess about this supplier, not something they told us."""
        return self.source == "business_default"


def resolve_lead_time(
    term_days: int | None,
    supplier_days: int | None,
    business_days: int | None = DEFAULT_LEAD_TIME_DAYS,
) -> LeadTime:
    """First value present wins. Zero is a real lead time (same day delivery), not missing."""
    if term_days is not None:
        return LeadTime(term_days, "product_term")
    if supplier_days is not None:
        return LeadTime(supplier_days, "supplier_default")
    return LeadTime(
        DEFAULT_LEAD_TIME_DAYS if business_days is None else business_days, "business_default"
    )


def next_delivery_date(earliest: date, delivery_weekdays: Collection[int] | None) -> date:
    """The first date on or after `earliest` that is a delivery day.

    `delivery_weekdays` uses ISO numbering (Monday 1 to Sunday 7). Without any, every day is a
    delivery day.
    """
    days = {d for d in (delivery_weekdays or ()) if 1 <= d <= 7}
    if not days:
        return earliest
    for offset in range(7):
        candidate = earliest + timedelta(days=offset)
        if candidate.isoweekday() in days:
            return candidate
    return earliest  # unreachable: a non empty set of valid weekdays always matches


def expected_delivery_date(
    order_date: date, lead: LeadTime, delivery_weekdays: Collection[int] | None
) -> date:
    """Order date plus lead time, moved forward to the supplier's next delivery day."""
    return next_delivery_date(order_date + timedelta(days=lead.days), delivery_weekdays)
