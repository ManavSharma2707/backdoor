"""Stock status, excess and ABC classes (`engine-spec.md` section 13)."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.engine.constants import ABC_A_SHARE, ABC_B_SHARE, AVAILABLE_SHARE_MIN
from app.engine.types import BoolArray, DemandClass, FloatArray


def abc_classes(revenue: Mapping[uuid.UUID, float]) -> dict[uuid.UUID, str]:
    """A, B or C by share of revenue: A is the top 70 percent, B the next 20, C the rest.

    A product is classed by the cumulative share *before* it, so the best seller is always an A
    even when it alone holds more than 70 percent. Products with no revenue are C.
    """
    total = sum(v for v in revenue.values() if v > 0)
    ranked = sorted(revenue.items(), key=lambda kv: (-kv[1], str(kv[0])))
    out: dict[uuid.UUID, str] = {}
    running = 0.0
    for pid, value in ranked:
        if value <= 0 or total <= 0:
            out[pid] = "C"
            continue
        out[pid] = "A" if running < ABC_A_SHARE else ("B" if running < ABC_B_SHARE else "C")
        running += value / total
    return out


@dataclass(frozen=True)
class StockStatus:
    status: str
    days_since_sale: int | None
    available_share: float
    reason: str | None = None


def stock_status(
    *,
    demand: FloatArray,
    available: BoolArray,
    as_of: date,
    start: date,
    age_days: int,
    demand_class: DemandClass,
    on_hand: float,
    days_of_cover: float | None,
    is_seasonal: bool,
    in_season: bool,
    nonmoving_days: int,
    slow_cover_days: int,
) -> StockStatus:
    """The status of one product, checked in this order:

    `new` (younger than the window), `unverified` (no sale in the window and not on the shelf
    70 percent of the time, so we cannot tell why), `non_moving` (no sale although it was on the
    shelf, stock on hand, not out of season), `slow` (has sales but more cover than the slow
    limit), otherwise `normal`.
    """
    window = min(nonmoving_days, demand.shape[0])
    sold = demand[-window:] > 0
    avail = available[-window:]
    share = float(avail.mean()) if window else 0.0
    sale_days = np.nonzero(demand > 0)[0]
    since = None
    if sale_days.size:
        since = (as_of - (start + timedelta(days=int(sale_days[-1])))).days - 1
    if age_days < nonmoving_days or demand_class in ("new", "no_history"):
        return StockStatus("new", since, share)
    if not sold.any():
        if share < AVAILABLE_SHARE_MIN:
            return StockStatus("unverified", since, share)
        if on_hand > 0 and not (is_seasonal and not in_season):
            return StockStatus("non_moving", since, share)
        return StockStatus("normal", since, share, "out_of_season" if is_seasonal else None)
    if days_of_cover is not None and days_of_cover >= slow_cover_days:
        return StockStatus("slow", since, share)
    return StockStatus("normal", since, share)


def excess_quantity(
    inventory_position: float, demand_to_horizon: float, safety_stock: float
) -> float:
    """`max(0, IP - (D over protection plus the excess horizon + SS))`."""
    return max(0.0, inventory_position - (demand_to_horizon + safety_stock))
