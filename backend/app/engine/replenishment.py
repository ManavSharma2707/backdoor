"""Order quantity per product (`engine-spec.md` section 10).

Money is `Decimal`, quantities are `float` inside the engine. Pack arithmetic is done in
`Decimal` after rounding the need to six places, so a need of 17.000000000000004 never costs an
extra pack.
"""

import math
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from statistics import NormalDist

from app.engine.constants import EXPIRY_CAP_DAYS_MAX
from app.engine.expiry import demand_between
from app.engine.lead_time import LeadTime, next_delivery_date, resolve_lead_time
from app.engine.types import FloatArray

PAISA = Decimal("0.01")
MIN_SERVICE = 0.5
MAX_SERVICE = 0.999


@dataclass(frozen=True)
class LeadTimeResult:
    base_days: int
    source: str
    effective_days: int  # until the first delivery weekday
    padding_days: int
    total_days: int
    arrival: date

    @property
    def is_assumed(self) -> bool:
        return self.source == "business_default"


def resolve_lead(
    as_of: date,
    term_days: int | None,
    supplier_days: int | None,
    business_days: int,
    delivery_weekdays: Collection[int] | None,
    padding_days: int = 0,
) -> LeadTimeResult:
    """Lead time of one product: term, supplier, business default, moved to the supplier's next
    delivery weekday, plus festival padding."""
    lead: LeadTime = resolve_lead_time(term_days, supplier_days, business_days)
    first = next_delivery_date(as_of + timedelta(days=lead.days), delivery_weekdays)
    effective = (first - as_of).days
    total = effective + padding_days
    return LeadTimeResult(
        lead.days, lead.source, effective, padding_days, total, as_of + timedelta(days=total)
    )


@dataclass(frozen=True)
class ReplenishInput:
    forecast: FloatArray  # daily from the plan date
    lead_days: int
    review_days: int
    usable: float
    incoming_confirmed: float
    incoming_by_arrival: float  # confirmed incoming that lands before the new order would
    reserved: float
    sigma_day: float
    service_level: float
    min_stock_qty: float
    pack_size: Decimal
    moq_units: Decimal
    shelf_life_days: int | None = None
    is_batch_tracked: bool = False
    sellable_fraction: float = 0.6
    pack_rounding: str = "up"


@dataclass
class ReplenishResult:
    protection_days: int
    demand_lead: float
    demand_protection: float
    inventory_position: float
    safety_stock: float
    target_level: float
    raw_qty: float
    suggested_qty: float
    packs: int
    pack_excess_qty: float
    cap_qty: float | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safety_stock(sigma_day: float, protection_days: int, service_level: float) -> float:
    """`z * sigma_day * sqrt(P)` with `z` from the normal distribution at the service level."""
    z = NormalDist().inv_cdf(min(max(service_level, MIN_SERVICE), MAX_SERVICE))
    return max(z * sigma_day * math.sqrt(max(protection_days, 0)), 0.0)


def _dec(value: float) -> Decimal:
    return Decimal(repr(round(value, 6)))


def round_to_packs(units: Decimal, pack: Decimal, mode: str = "up") -> int:
    rounding = ROUND_CEILING if mode == "up" else ROUND_FLOOR
    return int((units / pack).to_integral_value(rounding=rounding))


def replenish(inp: ReplenishInput) -> ReplenishResult:
    """Raw need, then minimum order, pack rounding and the shelf life cap.

    The need covers demand over the protection period (lead time plus review period) plus buffer
    stock, minus the stock position. Demand days are counted from the plan date: stock at the data
    cutoff serves the plan date itself, and a delivery on day `L` lands before that day's sales.
    """
    protection = inp.lead_days + inp.review_days
    d_lead = demand_between(inp.forecast, 0, inp.lead_days)
    d_protection = demand_between(inp.forecast, 0, protection)
    position = inp.usable + inp.incoming_confirmed - inp.reserved
    ss = safety_stock(inp.sigma_day, protection, inp.service_level)
    target = max(d_protection + ss, inp.min_stock_qty)
    raw = max(0.0, target - position)
    result = ReplenishResult(
        protection_days=protection,
        demand_lead=d_lead,
        demand_protection=d_protection,
        inventory_position=position,
        safety_stock=ss,
        target_level=target,
        raw_qty=raw,
        suggested_qty=0.0,
        packs=0,
        pack_excess_qty=0.0,
    )
    if raw <= 1e-9:
        return result
    pack = inp.pack_size if inp.pack_size > 0 else Decimal(1)
    need = _dec(raw)
    units = max(need, inp.moq_units)
    if inp.moq_units > need:
        result.reasons.append("MOQ_APPLIED")
    packs = round_to_packs(units, pack, "up")
    if inp.pack_rounding == "nearest_safe":
        excess = packs * pack - need
        covered = inp.usable + inp.incoming_by_arrival - inp.reserved >= d_lead + 0.5 * ss
        if excess > pack / 2 and covered:
            packs = round_to_packs(units, pack, "down")
    suggested = packs * pack

    if inp.is_batch_tracked and inp.shelf_life_days:
        cap_days = int(min(inp.shelf_life_days * inp.sellable_fraction, EXPIRY_CAP_DAYS_MAX))
        cap_qty = max(demand_between(inp.forecast, 0, cap_days) - position, 0.0)
        result.cap_qty = cap_qty
        cap_packs = round_to_packs(_dec(cap_qty), pack, "up")
        if packs > cap_packs:
            packs = cap_packs
            suggested = packs * pack
            result.reasons.append("EXPIRY_CAP")
            if 0 < suggested < inp.moq_units:
                packs, suggested = 0, Decimal(0)
                result.warnings.append("MOQ_VS_SHELF_LIFE")
    result.packs = packs
    result.suggested_qty = float(suggested)
    result.pack_excess_qty = max(float(suggested - need), 0.0) if packs else 0.0
    if packs and pack > 1 and result.pack_excess_qty > 0 and "EXPIRY_CAP" not in result.reasons:
        result.reasons.append("PACK_ROUNDING")
    return result


def spend(qty: float, unit_cost: Decimal | None) -> Decimal | None:
    """`quantity * unit cost` in whole paise, None when the cost is unknown."""
    if unit_cost is None:
        return None
    return (_dec(qty) * unit_cost).quantize(PAISA)
