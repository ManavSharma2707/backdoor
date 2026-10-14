"""Forecast methods. Each one has the same shape: `fit_predict(series, horizon_dates, ctx)`."""

from collections.abc import Callable, Sequence
from datetime import date

from app.engine.methods.base import MethodContext
from app.engine.methods.croston import croston_sba
from app.engine.methods.moving_average import moving_average
from app.engine.methods.naive import seasonal_naive
from app.engine.methods.prior import category_prior
from app.engine.methods.ses import ses_weekday
from app.engine.methods.weekday import weekday_profile
from app.engine.types import Forecast, Series

FitPredict = Callable[[Series, Sequence[date], MethodContext], Forecast]

STATISTICAL_METHODS: dict[str, FitPredict] = {
    "seasonal_naive": seasonal_naive,
    "moving_average": moving_average,
    "weekday_profile": weekday_profile,
    "ses_weekday": ses_weekday,
    "croston_sba": croston_sba,
    "category_prior": category_prior,
}

__all__ = [
    "STATISTICAL_METHODS",
    "FitPredict",
    "MethodContext",
    "category_prior",
    "croston_sba",
    "moving_average",
    "seasonal_naive",
    "ses_weekday",
    "weekday_profile",
]
