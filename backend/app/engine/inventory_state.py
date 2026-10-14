"""Stock at the plan date (`engine-spec.md` section 8): what is sellable, what is on the way.

Stock is read as it stood at the data cutoff. Expired and quarantined batches are shown but never
counted as usable. A purchase order past its expected date is reported and left out of the stock
the plan counts on.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.inputs import BatchInfo, ProductInfo


@dataclass(frozen=True)
class SellableBatch:
    batch_id: str | None
    batch_no: str | None
    qty: float
    expiry_date: date | None
    unit_cost: Decimal


@dataclass(frozen=True)
class Arrival:
    arrive_on: date
    qty: float
    po_number: str


@dataclass(frozen=True)
class OverduePo:
    po_number: str
    expected_date: date
    qty: float
    days_late: int


@dataclass
class StockState:
    on_hand_total: float = 0.0
    on_hand_sellable: float = 0.0
    expired_qty: float = 0.0
    expired_value: Decimal = Decimal(0)
    quarantined_qty: float = 0.0
    reserved: float = 0.0
    sellable: list[SellableBatch] = field(default_factory=list)
    expired: list[BatchInfo] = field(default_factory=list)
    confirmed: list[Arrival] = field(default_factory=list)
    overdue: list[OverduePo] = field(default_factory=list)

    @property
    def incoming_confirmed(self) -> float:
        return sum(a.qty for a in self.confirmed)

    @property
    def incoming_overdue(self) -> float:
        return sum(o.qty for o in self.overdue)

    def incoming_by(self, day: date) -> float:
        """Confirmed incoming that arrives on or before `day`."""
        return sum(a.qty for a in self.confirmed if a.arrive_on <= day)


def is_expired(batch: BatchInfo, as_of: date) -> bool:
    """A batch cannot be sold on or after its expiry date, or when it is flagged expired."""
    return batch.status == "expired" or (
        batch.expiry_date is not None and batch.expiry_date <= as_of
    )


def stock_state(product: ProductInfo, as_of: date, assumed_arrival: date) -> StockState:
    """Sellable batches in first expiry first out order, expired stock, and the open orders.

    An order without an expected date is assumed to arrive on `assumed_arrival`.
    """
    state = StockState()
    for b in product.batches:
        if b.qty <= 0:
            continue
        state.on_hand_total += b.qty
        state.reserved += b.reserved
        if is_expired(b, as_of):
            state.expired_qty += b.qty
            state.expired_value += Decimal(repr(round(b.qty, 6))) * b.unit_cost
            state.expired.append(b)
        elif b.status in ("quarantined", "closed"):
            state.quarantined_qty += b.qty
        else:
            state.on_hand_sellable += b.qty
            state.sellable.append(
                SellableBatch(
                    str(b.batch_id) if b.batch_id else None,
                    b.batch_no,
                    b.qty,
                    b.expiry_date,
                    b.unit_cost if b.unit_cost > 0 else product.avg_cost,
                )
            )
    state.sellable.sort(
        key=lambda s: (s.expiry_date is None, s.expiry_date or date.max, s.batch_no or "")
    )
    for line in product.incoming:
        if line.qty_open <= 0:
            continue
        if line.expected_date is not None and line.expected_date < as_of:
            state.overdue.append(
                OverduePo(
                    line.po_number,
                    line.expected_date,
                    line.qty_open,
                    (as_of - line.expected_date).days,
                )
            )
        else:
            state.confirmed.append(
                Arrival(line.expected_date or assumed_arrival, line.qty_open, line.po_number)
            )
    state.confirmed.sort(key=lambda a: (a.arrive_on, a.po_number))
    return state
