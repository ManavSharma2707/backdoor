"""Category prior, for products that are new or have no history."""

from collections.abc import Sequence
from datetime import date

from app.engine.constants import PRIOR_FACTOR
from app.engine.methods.base import MethodContext, flat
from app.engine.types import Forecast, Series


def category_prior(series: Series, horizon_dates: Sequence[date], ctx: MethodContext) -> Forecast:
    """The average daily demand of one product in the category, times 0.8. Always low confidence."""
    mean = ctx.category_mean or 0.0
    return Forecast("category_prior", flat(mean * PRIOR_FACTOR, len(horizon_dates)))
