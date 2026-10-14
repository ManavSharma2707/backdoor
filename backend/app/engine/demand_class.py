"""Demand classification (`engine-spec.md` section 4, Syntetos and Boylan)."""

from dataclasses import dataclass

import numpy as np

from app.engine.constants import (
    ADI_CUTOFF,
    CLASS_WINDOW_DAYS,
    CV2_CUTOFF,
    MIN_HISTORY_DAYS,
    MIN_TRUSTED_DAYS,
)
from app.engine.types import DemandClass, FloatArray


@dataclass(frozen=True)
class DemandProfile:
    demand_class: DemandClass
    trusted_days: int
    adi: float | None
    cv2: float | None
    mean_daily: float


def classify_demand(y: FloatArray, window_days: int = CLASS_WINDOW_DAYS) -> DemandProfile:
    """Class of one product from its training series (NaN = not trusted).

    ADI is the number of trusted days divided by the number of days with demand, which is the
    mean gap between demand days when gaps are counted in trusted days. CV2 is the squared
    coefficient of variation of the demand sizes. Below 28 trusted days the product is `new`,
    below 7 it has `no_history`.
    """
    tail = y[-window_days:]
    trusted = tail[~np.isnan(tail)]
    n = int(trusted.size)
    mean = float(trusted.mean()) if n else 0.0
    if n < MIN_HISTORY_DAYS:
        return DemandProfile("no_history", n, None, None, mean)
    if n < MIN_TRUSTED_DAYS:
        return DemandProfile("new", n, None, None, mean)
    sizes = trusted[trusted > 0]
    if sizes.size == 0:
        return DemandProfile("intermittent", n, None, None, 0.0)
    adi = n / sizes.size
    size_mean = float(sizes.mean())
    cv2 = float(sizes.var() / (size_mean * size_mean)) if size_mean > 0 else 0.0
    if adi < ADI_CUTOFF:
        label: DemandClass = "smooth" if cv2 < CV2_CUTOFF else "erratic"
    else:
        label = "intermittent" if cv2 < CV2_CUTOFF else "lumpy"
    return DemandProfile(label, n, float(adi), cv2, mean)


def segment_key(category_slug: str, demand_class: DemandClass) -> str:
    return f"{category_slug}|{demand_class}"
