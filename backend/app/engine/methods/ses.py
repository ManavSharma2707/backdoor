"""Simple exponential smoothing on the weekday adjusted series. Plain Python, no statsmodels."""

from collections.abc import Sequence
from datetime import date

import numpy as np

from app.engine.constants import SES_ALPHAS, SES_WINDOW_DAYS, WEEKDAY_MIN_DAYS
from app.engine.methods.base import MethodContext, flat, recent_mean, weekday_index
from app.engine.types import Forecast, Series

IDX_FLOOR = 0.1


def ses_level(z: list[float], alpha: float) -> tuple[float, float]:
    """Final level and one step in sample mean absolute error. `z` has no NaN."""
    level = z[0]
    total = 0.0
    for value in z[1:]:
        total += abs(value - level)
        level += alpha * (value - level)
    return level, total / max(len(z) - 1, 1)


def ses_weekday(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    """Deseasonalise with the raw weekday index, smooth, then put the shrunk weekday shape back.

    The raw index removes the weekly pattern completely from the series. A shrunk index would
    leave part of it behind, and the level would then follow whichever weekday the series ends
    on. The forecast uses the shrunk index, as the weekday profile does.

    `alpha` is the grid value with the lowest in sample one step error. Days that are not
    trusted are skipped, so the level carries over them.
    """
    n = len(horizon_dates)
    if len(series.y) < WEEKDAY_MIN_DAYS:
        return Forecast("ses_weekday", flat(recent_mean(series, ctx.window), n))
    _, idx = weekday_index(series)
    _, raw = weekday_index(series, shrink=False)
    window = series.tail(SES_WINDOW_DAYS)
    wd = window.weekdays()
    keep = ~np.isnan(window.y)
    if not keep.any():
        return Forecast("ses_weekday", flat(0.0, n))
    z = (window.y[keep] / np.maximum(raw[wd[keep]], IDX_FLOOR)).tolist()
    best_level, best_err = ses_level(z, SES_ALPHAS[0])
    for alpha in SES_ALPHAS[1:]:
        level, err = ses_level(z, alpha)
        if err < best_err:
            best_level, best_err = level, err
    out = np.array([best_level * idx[d.weekday()] for d in horizon_dates], dtype=np.float64)
    return Forecast("ses_weekday", np.maximum(out, 0.0))
