"""Feature building for the global model (`engine-spec.md` 5.3). Pure numpy.

Every feature of a row is known at its origin: lags are the latest observations of the target
weekday before the origin, rolling statistics stop at the origin, and the calendar and promotion
features describe the target date, which is known in advance.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from numpy.typing import NDArray

from app.engine.calendar import CalendarEvent
from app.engine.types import BoolArray, FloatArray, IntArray

Float32Array = NDArray[np.float32]
NEXT_FESTIVAL_CAP = 60
AGE_CAP = 730
LAGS = 4
ROLLING = (7, 28, 56)
LEVEL_WINDOW = 180

BASE_FEATURES = (
    *(f"lag_dow_{k}" for k in range(1, LAGS + 1)),
    *(f"mean_{w}" for w in ROLLING),
    "zero_share_28",
    "target_weekday",
    "target_dom",
    "target_month",
    "target_week",
    "h",
    "days_since_sale",
    "age_days",
    "price_ratio",
    "promo_flag",
    "next_festival_days",
    "level",
    "cv",
    "trusted_share_28",
    "category",
)


def event_feature_names(keys: Sequence[str]) -> list[str]:
    return [f"{k}_{w}" for k in keys for w in ("pre", "during", "post")]


@dataclass(frozen=True)
class FeatureInputs:
    """Products by days (history) and the calendar for every date through the horizon."""

    y: FloatArray  # trusted demand, NaN when not trusted
    start: date
    category_codes: IntArray
    promo: BoolArray  # products by (days + horizon)
    price_ratio: FloatArray  # products by days, latest price over the 90 day average
    events: Sequence[CalendarEvent]
    horizon: int = 28

    @property
    def n_days(self) -> int:
        return int(self.y.shape[1])


def event_keys(events: Sequence[CalendarEvent]) -> list[str]:
    return sorted({e.event_key for e in events})


def date_features(
    events: Sequence[CalendarEvent], start: date, n_dates: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Calendar columns, event flags and days to the next festival, for every date."""
    keys = event_keys(events)
    calendar = np.zeros((n_dates, 4), dtype=np.float64)
    flags = np.zeros((n_dates, 3 * len(keys)), dtype=np.float64)
    starts = sorted(e.start for e in events if e.kind == "festival")
    nxt = np.full(n_dates, NEXT_FESTIVAL_CAP, dtype=np.float64)
    for i in range(n_dates):
        d = start + timedelta(days=i)
        iso = d.isocalendar()
        calendar[i] = (d.weekday(), d.day, d.month, iso.week)
        for s in starts:
            if s >= d:
                nxt[i] = min((s - d).days, NEXT_FESTIVAL_CAP)
                break
    col = {k: j for j, k in enumerate(keys)}
    for event in events:
        for window, first, last in event.spans():
            a = max((first - start).days, 0)
            b = min((last - start).days, n_dates - 1)
            if b >= a:
                offset = {"pre": 0, "during": 1, "post": 2}[window]
                flags[a : b + 1, 3 * col[event.event_key] + offset] = 1.0
    return calendar, flags, nxt


class FeatureBuilder:
    """Builds the feature rows of an origin for every product and horizon step."""

    def __init__(self, inputs: FeatureInputs) -> None:
        self.inputs = inputs
        y = inputs.y
        valid = ~np.isnan(y)
        zero = valid & (y == 0)
        filled = np.where(valid, y, 0.0)
        self._cum_sum = _prefix(filled)
        self._cum_sq = _prefix(filled * filled)
        self._cum_n = _prefix(valid.astype(np.float64))
        self._cum_zero = _prefix(zero.astype(np.float64))
        n_products, n_days = y.shape
        sale = np.where(valid & (y > 0), np.arange(n_days)[None, :], -1)
        self._last_sale = np.maximum.accumulate(sale, axis=1)
        first = np.where(valid.any(axis=1), valid.argmax(axis=1), n_days)
        self._first_valid = first
        self.keys = event_keys(inputs.events)
        n_dates = n_days + inputs.horizon
        self._calendar, self._flags, self._next = date_features(
            inputs.events, inputs.start, n_dates
        )
        self.names = [*BASE_FEATURES, *event_feature_names(self.keys)]
        self.n_products = n_products

    @property
    def category_index(self) -> int:
        return self.names.index("category")

    def _window(self, o: int, w: int) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        lo = max(o - w, 0)
        n = self._cum_n[:, o] - self._cum_n[:, lo]
        s = self._cum_sum[:, o] - self._cum_sum[:, lo]
        q = self._cum_sq[:, o] - self._cum_sq[:, lo]
        z = self._cum_zero[:, o] - self._cum_zero[:, lo]
        return n, s, q, z

    def origin(self, o: int, horizon: int | None = None) -> Float32Array:
        """Feature tensor of shape (products, horizon, features) for the origin day index `o`.

        `o` is the index of the first forecast day, so only days `< o` are read.
        """
        h_total = horizon or self.inputs.horizon
        y = self.inputs.y
        n_products = self.n_products
        steps = np.arange(1, h_total + 1)
        target = o + steps - 1
        out = np.full((n_products, h_total, len(self.names)), np.nan, dtype=np.float32)

        weeks_back = -(-steps // 7)  # ceil(h / 7)
        for k in range(LAGS):
            idx = target - 7 * (weeks_back + k)
            ok = idx >= 0
            lag = np.full((n_products, h_total), np.nan)
            lag[:, ok] = y[:, idx[ok]]
            out[:, :, k] = lag
        for j, w in enumerate(ROLLING):
            n, s, _q, _z = self._window(o, w)
            mean = np.divide(s, n, out=np.full(n_products, np.nan), where=n > 0)
            out[:, :, LAGS + j] = mean[:, None]
        n28, _s, _q, z28 = self._window(o, 28)
        zero_share = np.divide(z28, n28, out=np.full(n_products, np.nan), where=n28 > 0)
        col = LAGS + len(ROLLING)
        out[:, :, col] = zero_share[:, None]
        cal = self._calendar[target]
        out[:, :, col + 1 : col + 5] = cal[None, :, :]
        out[:, :, col + 5] = steps[None, :]
        last = self._last_sale[:, o - 1] if o > 0 else np.full(n_products, -1)
        since = np.where(last >= 0, o - 1 - last, 365)
        out[:, :, col + 6] = np.minimum(since, 365)[:, None]
        age = np.where(self._first_valid < o, o - self._first_valid, 0)
        out[:, :, col + 7] = np.minimum(age, AGE_CAP)[:, None]
        price = self.inputs.price_ratio[:, o - 1] if o > 0 else np.ones(n_products)
        out[:, :, col + 8] = price[:, None]
        out[:, :, col + 9] = self.inputs.promo[:, target].astype(np.float64)
        out[:, :, col + 10] = self._next[target][None, :]
        nl, sl, ql, _zl = self._window(o, LEVEL_WINDOW)
        level = np.divide(sl, nl, out=np.full(n_products, np.nan), where=nl > 0)
        var = np.divide(ql, nl, out=np.full(n_products, np.nan), where=nl > 0) - level**2
        cv = np.divide(
            np.sqrt(np.maximum(var, 0.0)), level, out=np.full(n_products, np.nan), where=level > 0
        )
        out[:, :, col + 11] = level[:, None]
        out[:, :, col + 12] = cv[:, None]
        out[:, :, col + 13] = (n28 / 28.0)[:, None]
        out[:, :, col + 14] = self.inputs.category_codes[:, None]
        if self.keys:
            out[:, :, col + 15 :] = self._flags[target][None, :, :]
        return out

    def labels(self, o: int, horizon: int, limit: int) -> FloatArray:
        """Actual demand of every (product, step) of the origin; NaN beyond day `limit`
        (the end of the history that may be used) or on untrusted days."""
        steps = np.arange(horizon)
        target = o + steps
        out = np.full((self.n_products, horizon), np.nan, dtype=np.float64)
        ok = target < min(limit, self.inputs.n_days)
        out[:, ok] = self.inputs.y[:, target[ok]]
        return out


def _prefix(a: FloatArray) -> FloatArray:
    out = np.zeros((a.shape[0], a.shape[1] + 1), dtype=np.float64)
    np.cumsum(a, axis=1, out=out[:, 1:])
    return out


def price_ratio_matrix(units: FloatArray, revenue: FloatArray, window: int = 90) -> FloatArray:
    """Latest known price over the average price of the previous `window` days, per day.

    The price of a day is revenue over units, carried forward over days without sales. The ratio
    is 1 when there is not enough price history.
    """
    n_products, n_days = units.shape
    price = np.where(units > 0, revenue / np.maximum(units, 1e-9), np.nan)
    ratio = np.ones((n_products, n_days), dtype=np.float64)
    for p in range(n_products):
        row = price[p]
        known = ~np.isnan(row)
        if not known.any():
            continue
        idx = np.where(known, np.arange(n_days), -1)
        carried = row[np.maximum.accumulate(idx).clip(min=0)]
        carried[np.maximum.accumulate(idx) < 0] = np.nan
        cs = np.concatenate([[0.0], np.cumsum(np.where(np.isnan(carried), 0.0, carried))])
        cn = np.concatenate([[0.0], np.cumsum(~np.isnan(carried))])
        for t in range(n_days):
            lo = max(t - window + 1, 0)
            n = cn[t + 1] - cn[lo]
            if n > 0 and not np.isnan(carried[t]):
                ratio[p, t] = carried[t] / ((cs[t + 1] - cs[lo]) / n)
    return ratio
