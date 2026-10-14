"""What the services load for the engine: plain frozen records, no ORM objects.

Money and costs are `Decimal`. Stock quantities are `float` inside the engine and converted at
the boundary (`engine-spec.md` guiding rule: the engine may use float math, results are rounded
only for display and storage).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class SupplierInfo:
    id: uuid.UUID
    code: str
    name: str
    default_lead_time_days: int | None
    delivery_weekdays: tuple[int, ...] | None
    min_order_value: Decimal | None = None
    accepts_expiry_returns: bool = False
    expiry_return_window_days: int | None = None


@dataclass(frozen=True)
class TermInfo:
    """The primary supplier term of a product in force on the plan date."""

    supplier_id: uuid.UUID
    purchase_price: Decimal
    pack_size: Decimal
    moq_units: Decimal
    lead_time_days: int | None


@dataclass(frozen=True)
class BatchInfo:
    """Stock of one batch (or the batchless stock when `batch_id` is None)."""

    batch_id: uuid.UUID | None
    batch_no: str | None
    qty: float
    expiry_date: date | None
    unit_cost: Decimal
    status: str = "active"
    reserved: float = 0.0


@dataclass(frozen=True)
class IncomingLine:
    """Open quantity of a purchase order line that is sent or partly received."""

    po_id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    qty_open: float
    expected_date: date | None


@dataclass(frozen=True)
class ProductInfo:
    id: uuid.UUID
    sku: str
    name: str
    category_id: uuid.UUID
    category_slug: str
    category_name: str
    is_active: bool
    is_batch_tracked: bool
    shelf_life_days: int | None
    min_stock_qty: float
    is_seasonal: bool
    launched_on: date | None
    first_seen: date | None
    selling_price: Decimal
    mrp: Decimal
    base_unit: str
    pack_label: str | None
    avg_cost: Decimal
    term: TermInfo | None = None
    fallback_supplier_id: uuid.UUID | None = None
    previous_term_prices: tuple[Decimal, ...] = ()
    batches: tuple[BatchInfo, ...] = ()
    incoming: tuple[IncomingLine, ...] = ()
    last_count_date: date | None = None
    last_receipt_date: date | None = None

    @property
    def supplier_id(self) -> uuid.UUID | None:
        return self.term.supplier_id if self.term else self.fallback_supplier_id

    def age_days(self, as_of: date) -> int:
        """Days since launch (or since the first day with stock). 0 when unknown."""
        origin = self.launched_on or self.first_seen
        return max((as_of - origin).days, 0) if origin else 0

    @property
    def on_hand_total(self) -> float:
        return sum(b.qty for b in self.batches)


@dataclass(frozen=True)
class SettingsInfo:
    weekly_budget: Decimal | None = None
    service_level: float = 0.95
    review_period_days: int = 7
    default_lead_time_days: int = 3
    near_expiry_days: int = 90
    nonmoving_days: int = 60
    slow_cover_days: int = 90
    excess_horizon_days: int = 30
    forecast_horizon_days: int = 28
    backtest_origins: int = 12
    stale_count_days: int = 30
    sellable_shelf_life_fraction: float = 0.60
    censor_policy: str = "exclude"
    pack_rounding: str = "up"
    priority_weights: dict[str, float] = field(
        default_factory=lambda: {"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}
    )
    apply_festival_lead_padding: bool = True
