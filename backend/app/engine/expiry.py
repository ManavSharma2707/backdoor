"""First expired first out simulation over the horizon (`engine-spec.md` section 9)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from app.engine.constants import EXPIRY_EXTRAPOLATION_CAP_DAYS, EXTENSION_DAYS
from app.engine.types import FloatArray


@dataclass(frozen=True)
class SimBatch:
    """One lot in the simulation. `expiry_date` None means it never expires."""

    key: str
    qty: float
    expiry_date: date | None
    unit_cost: Decimal = Decimal(0)
    batch_no: str | None = None
    arrives_on: date | None = None  # set for lots that are still on the way


@dataclass
class BatchOutcome:
    key: str
    batch_no: str | None
    qty: float
    expiry_date: date | None
    expected_sold: float = 0.0
    expected_loss: float = 0.0
    unit_cost: Decimal = Decimal(0)
    days_to_expiry: int | None = None

    @property
    def loss_value(self) -> Decimal:
        return (Decimal(repr(round(self.expected_loss, 6))) * self.unit_cost).quantize(
            Decimal("0.01")
        )


@dataclass
class FefoResult:
    batches: list[BatchOutcome]
    consumed: float
    lost: float
    remaining: float
    start_stock: float
    arrivals: float
    daily_stock: list[float] = field(default_factory=list)

    @property
    def balance_error(self) -> float:
        """`start + arrivals - consumed - lost - remaining`, zero up to rounding."""
        return self.start_stock + self.arrivals - self.consumed - self.lost - self.remaining


def extend_forecast(forecast: FloatArray, n_days: int) -> FloatArray:
    """Pad the forecast to `n_days` with the average of its last 14 days."""
    if n_days <= len(forecast):
        return forecast[:n_days]
    tail = forecast[-EXTENSION_DAYS:]
    fill = float(tail.mean()) if len(tail) else 0.0
    return np.concatenate([forecast, np.full(n_days - len(forecast), fill)])


def demand_between(forecast: FloatArray, first: int, n_days: int) -> float:
    """Demand over `n_days` days starting `first` days after the plan date, flat beyond the
    forecast horizon."""
    if n_days <= 0:
        return 0.0
    return float(extend_forecast(forecast, first + n_days)[first : first + n_days].sum())


def simulate_fefo(
    batches: Sequence[SimBatch], forecast: FloatArray, as_of: date, horizon_days: int
) -> FefoResult:
    """Consume the forecast demand from the batch that expires first, day by day.

    On each day lots at or past their expiry date are written off, lots that arrive are added,
    then the day's demand is taken from the earliest expiring lot first. Lots that outlive the
    horizon are followed to their expiry date (at most 365 days) at the average demand of the last
    14 days of the forecast, so the expected loss of a slow lot is still seen.
    """
    expiries = [b.expiry_date for b in batches if b.expiry_date is not None and b.qty > 0]
    reach = horizon_days
    if expiries:
        reach = max(reach, min((max(expiries) - as_of).days + 1, EXPIRY_EXTRAPOLATION_CAP_DAYS))
    demand = extend_forecast(forecast, reach)
    lots = [
        BatchOutcome(
            b.key,
            b.batch_no,
            b.qty,
            b.expiry_date,
            unit_cost=b.unit_cost,
            days_to_expiry=(b.expiry_date - as_of).days if b.expiry_date else None,
        )
        for b in batches
    ]
    stock = [b.qty if b.arrives_on is None else 0.0 for b in batches]
    arrive = [(b.arrives_on - as_of).days if b.arrives_on else None for b in batches]
    order = sorted(
        range(len(batches)),
        key=lambda i: (batches[i].expiry_date is None, batches[i].expiry_date or date.max, i),
    )
    start = sum(b.qty for b in batches if b.arrives_on is None)
    incoming = 0.0
    consumed = lost = 0.0
    daily: list[float] = []
    for d in range(reach):
        day = as_of + timedelta(days=d)
        for i in order:
            if arrive[i] == d:
                stock[i] += batches[i].qty
                incoming += batches[i].qty
            exp = batches[i].expiry_date
            if exp is not None and exp <= day and stock[i] > 0:
                lots[i].expected_loss += stock[i]
                lost += stock[i]
                stock[i] = 0.0
        need = float(demand[d])
        for i in order:
            if need <= 0:
                break
            take = min(stock[i], need)
            if take > 0:
                stock[i] -= take
                lots[i].expected_sold += take
                consumed += take
                need -= take
        daily.append(sum(stock))
    return FefoResult(lots, consumed, lost, sum(stock), start, incoming, daily)
