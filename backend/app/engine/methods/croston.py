"""Croston with the Syntetos and Boylan bias correction, for intermittent demand."""

from collections.abc import Sequence
from datetime import date

import numpy as np

from app.engine.constants import CROSTON_ALPHA
from app.engine.methods.base import MethodContext, flat
from app.engine.types import Forecast, Series


def croston_rate(y: list[float], alpha: float = CROSTON_ALPHA) -> float:
    """Daily rate `(1 - alpha / 2) * z / p`.

    `z` is the smoothed size of a demand and `p` the smoothed number of trusted days between
    demands. `y` has no NaN. Without any demand the rate is 0.
    """
    size: float | None = None
    interval = 1.0
    gap = 1
    for value in y:
        if value > 0:
            if size is None:
                size, interval = value, float(gap)
            else:
                size += alpha * (value - size)
                interval += alpha * (gap - interval)
            gap = 1
        else:
            gap += 1
    if size is None:
        return 0.0
    return (1.0 - alpha / 2.0) * size / interval


def croston_sba(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    valid = series.y[~np.isnan(series.y)]
    return Forecast("croston_sba", flat(croston_rate(valid.tolist()), len(horizon_dates)))
