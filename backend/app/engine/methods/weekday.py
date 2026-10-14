"""Weekday profile: a level and a shrunk index per weekday."""

from collections.abc import Sequence
from datetime import date

import numpy as np

from app.engine.constants import WEEKDAY_MIN_DAYS
from app.engine.methods.base import MethodContext, flat, recent_mean, weekday_index
from app.engine.types import Forecast, Series


def weekday_profile(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    """`level * idx[weekday]`. With under six weeks of history it is the moving average."""
    if len(series.y) < WEEKDAY_MIN_DAYS:
        value = recent_mean(series, ctx.window)
        return Forecast("weekday_profile", flat(value, len(horizon_dates)))
    level, idx = weekday_index(series)
    out = np.array([level * idx[d.weekday()] for d in horizon_dates], dtype=np.float64)
    return Forecast("weekday_profile", np.maximum(out, 0.0))
