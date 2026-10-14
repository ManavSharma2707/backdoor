"""Daily rollup rules (`engine-spec.md` section 3). Pure: arrays in, arrays out.

Quantities arrive as whole thousandths (`int64`), so running stock is exact. The service reads
the ledger, calls these functions, and writes `daily_product_stats`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.engine.types import BoolArray, IntArray

AVAILABLE = "available"
STOCKED_OUT = "stocked_out_all_day"
SOLD_OUT = "sold_out_during_day"
NOT_LAUNCHED = "not_launched"
UNKNOWN = "unknown"
STATE_NAMES = (AVAILABLE, STOCKED_OUT, SOLD_OUT, NOT_LAUNCHED, UNKNOWN)
CENSORED_STATES = (STOCKED_OUT, SOLD_OUT)

_CODE = {name: i for i, name in enumerate(STATE_NAMES)}
_NEVER = np.iinfo(np.int64).max


@dataclass(frozen=True)
class Interval:
    """A recorded stockout. `end` is None while the product is still out."""

    start: date
    end: date | None


def running_balances(pre_qty: IntArray, net: IntArray) -> tuple[IntArray, IntArray]:
    """Opening and closing stock per product and day from the stock before the range and the
    net movement of each day. Shapes: `pre_qty` (P,), `net` (P, D)."""
    closing: IntArray = pre_qty[:, None] + np.cumsum(net, axis=1)
    opening: IntArray = closing - net
    return opening, closing


def forced_by_intervals(
    n_days: int, start: date, intervals_per_product: Sequence[Sequence[Interval]]
) -> BoolArray:
    """Mask (P, D) of days that fall inside a recorded stockout interval."""
    mask = np.zeros((len(intervals_per_product), n_days), dtype=np.bool_)
    last = start + timedelta(days=n_days - 1)
    for p, intervals in enumerate(intervals_per_product):
        for interval in intervals:
            lo = max((interval.start - start).days, 0)
            end = interval.end if interval.end is not None else last
            hi = min((end - start).days, n_days - 1)
            if hi >= lo:
                mask[p, lo : hi + 1] = True
    return mask


def classify_availability(
    *,
    start: date,
    opening: IntArray,
    closing: IntArray,
    receipts: IntArray,
    units_sold: IntArray,
    launched_on: Sequence[date | None],
    first_ledger_day: Sequence[date | None],
    forced: BoolArray,
) -> IntArray:
    """State code per product and day, in the order of the rules in the spec.

    1. `not_launched` before the launch date.
    2. `unknown` when the ledger has no history before the day.
    3. Stocked out at the start of the day with no receipt: `stocked_out_all_day`, or
       `sold_out_during_day` if something was sold anyway.
    4. A recorded stockout interval forces the same two states.
    5. Closing at zero after selling: `sold_out_during_day`.
    6. Otherwise `available`.
    """
    n_products, n_days = opening.shape
    day_ord = start.toordinal() + np.arange(n_days, dtype=np.int64)
    launch = np.array([d.toordinal() if d else -1 for d in launched_on], dtype=np.int64)
    first = np.array([d.toordinal() if d else _NEVER for d in first_ledger_day], dtype=np.int64)

    sold = units_sold > 0
    halted = ((opening <= 0) & (receipts <= 0)) | forced
    state = np.full((n_products, n_days), _CODE[AVAILABLE], dtype=np.int64)
    state[(closing <= 0) & sold] = _CODE[SOLD_OUT]
    state[halted & ~sold] = _CODE[STOCKED_OUT]
    state[halted & sold] = _CODE[SOLD_OUT]
    state[first[:, None] >= day_ord[None, :]] = _CODE[UNKNOWN]
    state[(launch[:, None] >= 0) & (day_ord[None, :] < launch[:, None])] = _CODE[NOT_LAUNCHED]
    return state


def state_names(codes: IntArray) -> list[list[str]]:
    return [[STATE_NAMES[int(c)] for c in row] for row in codes]


def is_censored(codes: IntArray) -> BoolArray:
    result: BoolArray = (codes == _CODE[STOCKED_OUT]) | (codes == _CODE[SOLD_OUT])
    return result


@dataclass(frozen=True)
class Run:
    first: date
    last: date

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def stockout_runs(codes_row: IntArray, start: date, min_days: int) -> list[Run]:
    """Consecutive days of `stocked_out_all_day` that last at least `min_days`."""
    flag = codes_row == _CODE[STOCKED_OUT]
    runs: list[Run] = []
    begin: int | None = None
    for i, value in enumerate([*flag.tolist(), False]):
        if value and begin is None:
            begin = i
        elif not value and begin is not None:
            if i - begin >= min_days:
                runs.append(Run(start + timedelta(days=begin), start + timedelta(days=i - 1)))
            begin = None
    return runs
