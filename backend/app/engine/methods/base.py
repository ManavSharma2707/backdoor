"""What every method receives besides the series."""

from dataclasses import dataclass

import numpy as np

from app.engine.constants import (
    MA_WINDOW_INTERMITTENT,
    MA_WINDOW_SMOOTH,
    WEEKDAY_SHRINK_K,
    WEEKDAY_WEEKS,
)
from app.engine.types import DemandClass, FloatArray, Series, nan_mean


@dataclass(frozen=True)
class MethodContext:
    """`category_mean` is the average daily demand of one product in the category (the prior)."""

    demand_class: DemandClass = "smooth"
    category_mean: float | None = None
    moving_average_window: int | None = None

    @property
    def window(self) -> int:
        if self.moving_average_window is not None:
            return self.moving_average_window
        if self.demand_class in ("intermittent", "lumpy"):
            return MA_WINDOW_INTERMITTENT
        return MA_WINDOW_SMOOTH


def flat(value: float, n: int) -> FloatArray:
    return np.full(n, max(value, 0.0), dtype=np.float64)


def recent_mean(series: Series, window: int) -> float:
    """Mean of the trusted days among the last `window` days. When there are none, the mean of
    the last `window` trusted days anywhere in the history, and 0 when the history has none."""
    y = series.y
    tail = y[-window:]
    valid = tail[~np.isnan(tail)]
    if valid.size:
        return float(valid.mean())
    anywhere = y[~np.isnan(y)]
    return float(anywhere[-window:].mean()) if anywhere.size else 0.0


def weekday_index(
    series: Series, weeks: int = WEEKDAY_WEEKS, *, shrink: bool = True
) -> tuple[float, FloatArray]:
    """Level and weekday indices over the last `weeks` weeks.

    `idx[d] = 1 + (raw - 1) * n_d / (n_d + 4)` with `raw = mean(y on weekday d) / level`.
    A weekday with no observation keeps the index 1. With `shrink=False` the raw index is
    returned (used to deseasonalise a series, so that nothing of the weekly shape is left).
    """
    window = series.tail(weeks * 7)
    level = nan_mean(window.y)
    idx = np.ones(7, dtype=np.float64)
    if level <= 0:
        return level, idx
    wd = window.weekdays()
    for d in range(7):
        values = window.y[(wd == d) & ~np.isnan(window.y)]
        n = values.size
        if n:
            raw = float(values.mean()) / level
            idx[d] = 1.0 + (raw - 1.0) * n / (n + WEEKDAY_SHRINK_K) if shrink else raw
    return level, idx
