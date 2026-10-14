"""Stockout risk (`engine-spec.md` section 11)."""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np

from app.engine.constants import (
    DAYS_OF_COVER_WINDOW,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_MEDIUM,
)
from app.engine.expiry import extend_forecast
from app.engine.inventory_state import Arrival
from app.engine.types import FloatArray, RiskLevel

NORMAL = NormalDist()


def stockout_probability(
    stock_before_arrival: float, demand_lead: float, sigma_lead: float
) -> float:
    """`1 - Phi((S_L - D_L) / sigma_L)`, the chance that demand before the delivery exceeds the
    stock that will be there. With no spread it is 1 when stock falls short and 0 otherwise."""
    if sigma_lead <= 0:
        return 1.0 if stock_before_arrival < demand_lead else 0.0
    return float(
        min(max(1.0 - NORMAL.cdf((stock_before_arrival - demand_lead) / sigma_lead), 0.0), 1.0)
    )


def expected_units_short(stock: float, demand: float, sigma: float) -> float:
    """Expected shortfall of a normal demand: `sigma * (phi(z) - z * (1 - Phi(z)))`."""
    if sigma <= 0:
        return max(demand - stock, 0.0)
    z = (stock - demand) / sigma
    return float(max(sigma * (NORMAL.pdf(z) - z * (1.0 - NORMAL.cdf(z))), 0.0))


def projected_stockout_date(
    usable: float, arrivals: list[Arrival], forecast: FloatArray, as_of: date, horizon: int
) -> date | None:
    """The first day the cumulative forecast exceeds the usable stock plus arrivals so far."""
    demand = extend_forecast(forecast, horizon)
    stock = usable
    cumulative = 0.0
    for d in range(horizon):
        day = as_of + timedelta(days=d)
        stock += sum(a.qty for a in arrivals if a.arrive_on == day)
        cumulative += float(demand[d])
        if cumulative > stock + 1e-9:
            return day
    return None


def days_of_cover(usable: float, forecast: FloatArray) -> float | None:
    """Usable stock over the average daily forecast of the next 14 days (None when it is 0)."""
    avg = float(extend_forecast(forecast, DAYS_OF_COVER_WINDOW).mean())
    return usable / avg if avg > 1e-9 else None


@dataclass(frozen=True)
class RiskInput:
    usable: float
    avg_forecast: float
    probability: float
    stockout_on: date | None
    arrival: date
    service_level: float
    order_suggested: bool


def classify_risk(r: RiskInput) -> RiskLevel:
    """The level from the table of `engine-spec.md` 11.

    A line is `medium` also when its stockout chance is under 10 percent but still above what the
    service level allows (1 minus the service level): the buffer is eaten into even though a
    stockout is unlikely. This replaces the spec wording "IP < D_P + SS", which every line that
    needs an order satisfies, so it could not tell a mild risk from a normal reorder.
    """
    p = r.probability
    if (r.usable <= 0 and r.avg_forecast > 0) or p >= RISK_CRITICAL:
        return "critical"
    if r.stockout_on is not None and r.stockout_on <= r.arrival:
        return "critical"
    if p >= RISK_HIGH:
        return "high"
    if p >= RISK_MEDIUM or p > 1.0 - r.service_level:
        return "medium"
    return "low" if r.order_suggested else "none"


def sigma_lead(sigma_day: float, lead_days: int) -> float:
    return sigma_day * math.sqrt(max(lead_days, 0))


def nan_safe(values: FloatArray) -> FloatArray:
    return np.nan_to_num(values, nan=0.0)
