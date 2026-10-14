"""Training series and one product forecast (`engine-spec.md` section 5).

The history is a matrix of products by days. A day is trusted when the product was available
and no promotion ran. Everything else is NaN, so statistical methods average over what was
really observed and never learn from a shelf that was empty.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.engine.backtest import STAT_CANDIDATES
from app.engine.calendar import CalendarEvent
from app.engine.constants import (
    CENSORED_SHARE_WARN,
    CENSORED_WINDOW_DAYS,
    PRIOR_WINDOW_DAYS,
)
from app.engine.demand_class import segment_key
from app.engine.event_effects import EffectRecord, PromoOccurrence, multiplier_timeline
from app.engine.methods import STATISTICAL_METHODS, MethodContext
from app.engine.rollup import AVAILABLE as AVAILABLE_STATE
from app.engine.rollup import SOLD_OUT, STATE_NAMES, STOCKED_OUT
from app.engine.selection import SegmentInfo, Selection, interval
from app.engine.types import BoolArray, DemandClass, FloatArray, Forecast, IntArray, Series

AVAILABLE_CODE = STATE_NAMES.index(AVAILABLE_STATE)
SOLD_OUT_CODE = STATE_NAMES.index(SOLD_OUT)
STOCKED_OUT_CODE = STATE_NAMES.index(STOCKED_OUT)


@dataclass(frozen=True)
class TrainingData:
    """Products by days, ending the day before `as_of`.

    `trusted` is demand on available days without a promotion (NaN elsewhere). `with_promo`
    keeps the promotion days. `censored` marks sold out and stocked out days.
    """

    start: date
    trusted: FloatArray
    with_promo: FloatArray
    censored: BoolArray
    fill_used: BoolArray

    @property
    def n_days(self) -> int:
        return int(self.trusted.shape[1])


def training_data(
    units: FloatArray, codes: IntArray, promo: BoolArray, start: date, policy: str = "exclude"
) -> TrainingData:
    """Build the training matrices from demand (sold minus restocked returns) and availability.

    With `policy = "weekday_fill"` censored days are replaced by what the weekday profile of the
    four weeks before expected (never below what was actually sold). The report always flags
    that a fill was used.
    """
    demand = np.maximum(units, 0.0)
    available = codes == AVAILABLE_CODE
    censored = (codes == SOLD_OUT_CODE) | (codes == STOCKED_OUT_CODE)
    with_promo = np.where(available, demand, np.nan)
    trusted = np.where(available & ~promo, demand, np.nan)
    fill_used = np.zeros_like(censored)
    if policy == "weekday_fill":
        trusted, with_promo, fill_used = _fill_censored(
            trusted, with_promo, demand, censored, codes == SOLD_OUT_CODE, promo, start
        )
    return TrainingData(start, trusted, with_promo, censored, fill_used)


def _fill_censored(
    trusted: FloatArray,
    with_promo: FloatArray,
    demand: FloatArray,
    censored: BoolArray,
    sold_out: BoolArray,
    promo: BoolArray,
    start: date,
) -> tuple[FloatArray, FloatArray, BoolArray]:
    fill_used = np.zeros_like(censored)
    wd0 = start.toordinal() - 1
    for p, t in zip(*np.nonzero(censored & ~promo), strict=True):
        past = trusted[p, max(0, t - 28) : t]
        same = past[(((wd0 + np.arange(max(0, t - 28), t)) % 7) == (wd0 + t) % 7)]
        same = same[~np.isnan(same)]
        base = same if same.size else past[~np.isnan(past)]
        if not base.size:
            continue
        estimate = float(base.mean())
        value = max(estimate, float(demand[p, t])) if sold_out[p, t] else estimate
        trusted[p, t] = value
        with_promo[p, t] = value
        fill_used[p, t] = True
    return trusted, with_promo, fill_used


def censored_share(censored: BoolArray) -> FloatArray:
    """Share of the last 56 days that was censored, per product."""
    window = censored[:, -CENSORED_WINDOW_DAYS:]
    return window.mean(axis=1) if window.shape[1] else np.zeros(censored.shape[0])


def censored_warning(share: float) -> bool:
    return share > CENSORED_SHARE_WARN


def category_means(
    trusted: FloatArray, category_codes: IntArray, n_categories: int, eligible: BoolArray
) -> FloatArray:
    """Mean daily demand of one product per category over the last 56 days, using only the
    eligible products (those with enough history). NaN when the category has none."""
    window = trusted[:, -PRIOR_WINDOW_DAYS:]
    valid = ~np.isnan(window)
    count = valid.sum(axis=1)
    totals = np.where(valid, window, 0.0).sum(axis=1)
    per_product = np.divide(totals, count, out=np.full(len(count), np.nan), where=count > 0)
    means = np.full(n_categories, np.nan, dtype=np.float64)
    for code in range(n_categories):
        sel = eligible & (category_codes == code) & ~np.isnan(per_product)
        if sel.any():
            means[code] = float(per_product[sel].mean())
    return means


def adjust_for_effects(y: FloatArray, multipliers: FloatArray) -> FloatArray:
    """Divide the effect out of the training series, so the level is what the product sells
    without the festival or season. Days without an applied effect have multiplier 1."""
    return y / multipliers


def fit_forecast(
    method: str,
    y: FloatArray,
    start: date,
    horizon_dates: Sequence[date],
    ctx: MethodContext,
    horizon_multipliers: FloatArray | None = None,
) -> Forecast:
    """One product, one method. The learned multipliers scale the horizon of statistical methods
    (the global model learns events itself and is not passed any)."""
    fn = STATISTICAL_METHODS[method]
    forecast = fn(Series(start, y), horizon_dates, ctx)
    if horizon_multipliers is None:
        return forecast
    return Forecast(forecast.method, np.maximum(forecast.yhat * horizon_multipliers, 0.0))


@dataclass
class ProductForecast:
    """The forecast of one product for the plan horizon."""

    method: str
    yhat: FloatArray
    lower: FloatArray
    upper: FloatArray
    base: FloatArray
    multiplier: FloatArray
    event_keys: list[str | None]
    segment: str | None
    interval: SegmentInfo | None


def effect_matrices(
    records: Sequence[EffectRecord],
    events: Sequence[CalendarEvent],
    *,
    category_keys: Sequence[str],
    category_codes: IntArray,
    promotions: Sequence[PromoOccurrence],
    start: date,
    n_days: int,
) -> tuple[FloatArray, list[list[str | None]]]:
    """Applied multiplier per product and day (history and horizon), and the event key of each
    horizon-or-history day. Category timelines are shared, products with a promotion of their
    own get theirs."""
    n_products = len(category_codes)
    mult = np.ones((n_products, n_days), dtype=np.float64)
    keys: list[list[str | None]] = [[] for _ in range(n_products)]
    by_category: dict[int, tuple[FloatArray, list[str | None]]] = {}
    own_promos: dict[int, list[PromoOccurrence]] = {}
    category_promos = [pr for pr in promotions if pr.product_index is None]
    for promo in promotions:
        if promo.product_index is not None:
            own_promos.setdefault(promo.product_index, []).append(promo)
    for p in range(n_products):
        code = int(category_codes[p])
        if p in own_promos:
            m, k = multiplier_timeline(
                records,
                events,
                category_keys[code],
                start,
                n_days,
                [*category_promos, *own_promos[p]],
                product_index=p,
            )
        else:
            if code not in by_category:
                by_category[code] = multiplier_timeline(
                    records, events, category_keys[code], start, n_days, category_promos
                )
            m, k = by_category[code]
        mult[p] = m
        keys[p] = k
    return mult, keys


def forecast_products(
    *,
    y_adjusted: FloatArray,
    start: date,
    as_of: date,
    horizon: int,
    classes: Sequence[DemandClass],
    category_keys: Sequence[str],
    category_slugs: Sequence[str],
    category_means: Sequence[float | None],
    selection: Selection,
    multipliers: FloatArray,
    event_keys: Sequence[Sequence[str | None]],
    global_forecast: FloatArray | None = None,
    allow_global: bool = False,
) -> list[ProductForecast]:
    """Forecast every product with the method its segment selected.

    New products use the moving average on the days they have, products with almost no history
    use the category prior. The global model, when allowed and selected, is used as is: it learns
    festivals itself, so no multiplier is applied to it.
    """
    n_days = y_adjusted.shape[1]
    dates = [as_of + timedelta(days=i) for i in range(horizon)]
    out: list[ProductForecast] = []
    for p, klass in enumerate(classes):
        series = y_adjusted[p]
        ctx = MethodContext(demand_class=klass, category_mean=category_means[p])
        seg_key = segment_key(category_slugs[p], klass)
        info: SegmentInfo | None = None
        if klass == "no_history":
            method = "category_prior"
        elif klass == "new":
            method = "moving_average"
        else:
            method, info = selection.resolve(seg_key, klass, allow_lgbm=allow_global)
            if method == "lightgbm_global" and global_forecast is None:
                method = info.selected_stat if info else "moving_average"
        mult = multipliers[p, n_days : n_days + horizon]
        keys = list(event_keys[p][n_days : n_days + horizon])
        if method == "lightgbm_global" and global_forecast is not None:
            base = np.maximum(global_forecast[p, :horizon], 0.0)
            applied = np.ones(horizon, dtype=np.float64)
            keys = [None] * horizon
            yhat = base.copy()
        else:
            base = fit_forecast(method, series, start, dates, ctx).yhat
            applied = mult
            yhat = np.maximum(base * applied, 0.0)
        lower, upper = interval(yhat, info)
        out.append(
            ProductForecast(
                method,
                yhat,
                lower,
                upper,
                base,
                applied,
                keys,
                seg_key if klass in STAT_CANDIDATES else None,
                info,
            )
        )
    return out
