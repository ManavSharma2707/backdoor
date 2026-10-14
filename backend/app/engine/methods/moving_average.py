"""Moving average of the trusted days, the parsimony anchor."""

from collections.abc import Sequence
from datetime import date

from app.engine.methods.base import MethodContext, flat, recent_mean
from app.engine.types import Forecast, Series


def moving_average(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    """Flat forecast at the mean of the last `w` days (28, or 56 for intermittent demand)."""
    return Forecast("moving_average", flat(recent_mean(series, ctx.window), len(horizon_dates)))
