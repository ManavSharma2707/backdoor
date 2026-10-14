"""Rolling origin backtest (`engine-spec.md` section 6.1).

At every weekly origin each candidate method is fitted on the days before the origin only, and
forecasts the next 7 days. Forecasts are compared with what sold on the trusted days of that
week. Nothing after the origin is ever passed to a method.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from app.engine.constants import BACKTEST_HORIZON, BACKTEST_ORIGINS
from app.engine.methods import STATISTICAL_METHODS, MethodContext
from app.engine.types import DemandClass, FloatArray, IntArray, Series

BASELINE_28 = "moving_average_28"
STAT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "smooth": ("seasonal_naive", "moving_average", "weekday_profile", "ses_weekday"),
    "erratic": ("seasonal_naive", "moving_average", "weekday_profile", "ses_weekday"),
    "intermittent": ("moving_average", "croston_sba", "weekday_profile"),
    "lumpy": ("moving_average", "croston_sba", "weekday_profile"),
}
REFERENCE_METHODS = ("seasonal_naive", BASELINE_28)
ALL_STAT = ("seasonal_naive", "moving_average", "weekday_profile", "ses_weekday", "croston_sba")


@dataclass(frozen=True)
class Metrics:
    n_points: int
    mae: float
    rmse: float
    wape: float | None
    bias: float | None
    mean_actual: float
    coverage: float

    def stored(self) -> "Metrics":
        """The metrics as the database keeps them (4 places, coverage 3). A fresh backtest and a
        reloaded one then give the same plan to the last digit."""
        return Metrics(
            self.n_points,
            round(self.mae, 4),
            round(self.rmse, 4),
            None if self.wape is None else round(self.wape, 4),
            None if self.bias is None else round(self.bias, 4),
            round(self.mean_actual, 4),
            round(self.coverage, 3),
        )

    @property
    def mae_ratio(self) -> float | None:
        """MAE over the mean actual demand, the scale free error of intermittent products."""
        return self.mae / self.mean_actual if self.mean_actual > 0 else None


@dataclass
class ErrorSet:
    """Actuals and forecasts of one product and method on the trusted target days."""

    actual: list[float] = field(default_factory=list)
    forecast: list[float] = field(default_factory=list)
    rank: list[int] = field(default_factory=list)  # origin number, 0 is the oldest

    def arrays(self, min_rank: int = 0) -> tuple[FloatArray, FloatArray]:
        rank = np.array(self.rank, dtype=np.int64)
        keep = rank >= min_rank
        a = np.array(self.actual, dtype=np.float64)[keep]
        f = np.array(self.forecast, dtype=np.float64)[keep]
        return a, f


@dataclass
class BacktestData:
    """Everything a backtest measured, before any aggregation."""

    n_origins: int
    origins: list[date]
    errors: list[dict[str, ErrorSet]]  # per product, per method
    coverage: list[float]  # per product: trusted target days over all target days
    horizon: int = BACKTEST_HORIZON


def compute_metrics(a: FloatArray, f: FloatArray, coverage: float) -> Metrics:
    n = int(a.size)
    if n == 0:
        return Metrics(0, 0.0, 0.0, None, None, 0.0, coverage)
    err = f - a
    abs_err = np.abs(err)
    total = float(a.sum())
    return Metrics(
        n_points=n,
        mae=float(abs_err.mean()),
        rmse=float(np.sqrt((err * err).mean())),
        wape=float(abs_err.sum() / total) if total > 0 else None,
        bias=float(err.sum() / total) if total > 0 else None,
        mean_actual=float(a.mean()),
        coverage=coverage,
    )


def origin_dates(as_of: date, n_origins: int) -> list[date]:
    """The weekly origins, oldest first. The newest is a week before `as_of`."""
    return [as_of - timedelta(days=7 * k) for k in range(n_origins, 0, -1)]


def run_backtest(
    *,
    y_train: FloatArray,
    y_eval: FloatArray,
    multipliers: FloatArray | None,
    start: date,
    classes: Sequence[DemandClass],
    category_means: Sequence[float | None],
    n_origins: int = BACKTEST_ORIGINS,
    methods: Mapping[str, tuple[str, ...]] | None = None,
    extra: Mapping[str, Mapping[tuple[int, int], FloatArray]] | None = None,
    horizon: int = BACKTEST_HORIZON,
) -> BacktestData:
    """Back test every product with the candidate methods of its class.

    `y_train` is the (effect adjusted) training series, NaN where a day is not trusted.
    `y_eval` holds what really sold on the trusted days and NaN elsewhere. `multipliers`
    (products by days plus horizon) are the learned effects, applied to the forecast of the
    statistical methods. `extra` carries forecasts made elsewhere (the global model), keyed by
    method, then `(product index, origin number)`.
    """
    n_products, n_days = y_train.shape
    candidates = methods or STAT_CANDIDATES
    origins = origin_dates(start + timedelta(days=n_days), n_origins)
    errors: list[dict[str, ErrorSet]] = [{} for _ in range(n_products)]
    coverage = [0.0] * n_products
    for p in range(n_products):
        klass = classes[p]
        if klass in ("new", "no_history"):
            continue
        names = set(candidates.get(klass, ())) | set(REFERENCE_METHODS)
        sets = {name: ErrorSet() for name in names}
        ctx = MethodContext(demand_class=klass, category_mean=category_means[p])
        ctx28 = MethodContext(demand_class=klass, moving_average_window=28)
        trusted_total = 0
        for rank, origin in enumerate(origins):
            o = (origin - start).days
            series = Series(start, y_train[p, :o])
            dates = [origin + timedelta(days=i) for i in range(horizon)]
            actual = y_eval[p, o : o + horizon]
            ok = ~np.isnan(actual)
            trusted_total += int(ok.sum())
            mult = multipliers[p, o : o + horizon] if multipliers is not None else None
            for name in names:
                if name == BASELINE_28:
                    forecast = STATISTICAL_METHODS["moving_average"](series, dates, ctx28).yhat
                else:
                    forecast = STATISTICAL_METHODS[name](series, dates, ctx).yhat
                if mult is not None:
                    forecast = np.maximum(forecast * mult, 0.0)
                _record(sets[name], actual, ok, forecast, rank)
        for method, table in (extra or {}).items():
            es = ErrorSet()
            for rank, origin in enumerate(origins):
                extra_forecast = table.get((p, rank))
                if extra_forecast is None:
                    continue
                o = (origin - start).days
                actual = y_eval[p, o : o + horizon]
                _record(es, actual, ~np.isnan(actual), extra_forecast, rank)
            sets[method] = es
        errors[p] = sets
        coverage[p] = trusted_total / (n_origins * horizon)
    return BacktestData(n_origins, origins, errors, coverage, horizon)


def _record(
    target: ErrorSet, actual: FloatArray, ok: np.ndarray, forecast: FloatArray, rank: int
) -> None:
    for a, f in zip(actual[ok], forecast[: len(actual)][ok], strict=True):
        target.actual.append(float(a))
        target.forecast.append(float(f))
        target.rank.append(rank)


def pooled(
    data: BacktestData, products: Sequence[int], method: str, min_rank: int = 0
) -> tuple[FloatArray, FloatArray]:
    """Actuals and forecasts of `method` over the given products."""
    a_parts: list[FloatArray] = []
    f_parts: list[FloatArray] = []
    for p in products:
        es = data.errors[p].get(method)
        if es is None or not es.actual:
            continue
        a, f = es.arrays(min_rank)
        a_parts.append(a)
        f_parts.append(f)
    if not a_parts:
        empty = np.zeros(0, dtype=np.float64)
        return empty, empty
    return np.concatenate(a_parts), np.concatenate(f_parts)


def product_metrics(data: BacktestData, p: int, method: str, min_rank: int = 0) -> Metrics | None:
    es = data.errors[p].get(method)
    if es is None or not es.actual:
        return None
    a, f = es.arrays(min_rank)
    return compute_metrics(a, f, data.coverage[p])


def category_codes_of(slugs: Sequence[str]) -> tuple[IntArray, list[str]]:
    keys = sorted(set(slugs))
    index = {k: i for i, k in enumerate(keys)}
    return np.array([index[s] for s in slugs], dtype=np.int64), keys
