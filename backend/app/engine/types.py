"""Shared array aliases and small value types for the engine."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

DemandClass = Literal["smooth", "erratic", "intermittent", "lumpy", "new", "no_history"]
Confidence = Literal["high", "medium", "low"]
RiskLevel = Literal["critical", "high", "medium", "low", "none"]
Provenance = Literal["observed", "calculated", "assumed"]


@dataclass(frozen=True)
class Series:
    """Daily demand ending the day before `origin`.

    `y[i]` belongs to `start + i days`. NaN marks a day that must not be learned from
    (stocked out, promotion, not launched). Nothing in a series is ever after the origin.
    """

    start: date
    y: FloatArray

    @property
    def origin(self) -> date:
        return self.start + timedelta(days=len(self.y))

    def weekdays(self) -> IntArray:
        """Weekday of every element, Monday is 0."""
        base = self.start.toordinal() - 1
        return (base + np.arange(len(self.y), dtype=np.int64)) % 7

    def tail(self, days: int) -> "Series":
        n = min(days, len(self.y))
        return Series(self.origin - timedelta(days=n), self.y[len(self.y) - n :])


@dataclass(frozen=True)
class Forecast:
    method: str
    yhat: FloatArray


def weekday_of(day: date) -> int:
    return day.weekday()


def nan_mean(values: FloatArray) -> float:
    """Mean ignoring NaN, 0.0 when nothing is left."""
    valid = values[~np.isnan(values)]
    return float(valid.mean()) if valid.size else 0.0
