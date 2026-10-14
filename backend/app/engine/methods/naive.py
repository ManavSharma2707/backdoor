"""Seasonal naive: the same weekday last week."""

from collections.abc import Sequence
from datetime import date

import numpy as np

from app.engine.methods.base import MethodContext, recent_mean
from app.engine.types import Forecast, Series

LOOKBACK_WEEKS = 8


def seasonal_naive(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    """`y[t - 7]`, stepping back whole weeks from the target until a trusted day is found.

    Targets more than a week ahead use the latest observed day of the same weekday, so the
    forecast never reads a value after the origin. With no trusted day of that weekday in the
    last eight weeks it falls back to the mean of the last 56 days.
    """
    n = len(series.y)
    fallback = recent_mean(series, 56)
    out = np.zeros(len(horizon_dates), dtype=np.float64)
    for i, day in enumerate(horizon_dates):
        offset = (day - series.start).days  # index the target day would have in the series
        first_back = 1 if offset < n + 7 else -(-(offset - n + 1) // 7)
        value = float("nan")
        for k in range(LOOKBACK_WEEKS):
            idx = offset - 7 * (first_back + k)
            if 0 <= idx < n and not np.isnan(series.y[idx]):
                value = float(series.y[idx])
                break
        out[i] = fallback if np.isnan(value) else value
    return Forecast("seasonal_naive", np.maximum(out, 0.0))
