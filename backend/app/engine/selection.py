"""Method selection per segment and the confidence label (`engine-spec.md` 6.2 and 6.4)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.engine.backtest import (
    BASELINE_28,
    STAT_CANDIDATES,
    BacktestData,
    Metrics,
    compute_metrics,
    pooled,
    product_metrics,
)
from app.engine.constants import (
    CENSORED_SHARE_HIGH_CONFIDENCE,
    HIGH_COVERAGE,
    HIGH_WAPE,
    INTERMITTENT_MAE_RATIO,
    INTERVAL_LOWER_Q,
    INTERVAL_UPPER_Q,
    LGBM_BACKTEST_ORIGINS,
    MEDIUM_COVERAGE,
    MEDIUM_WAPE,
    MIN_SEGMENT_POINTS,
    MIN_SEGMENT_PRODUCTS,
    PARSIMONY,
)
from app.engine.demand_class import segment_key
from app.engine.types import Confidence, DemandClass

ANCHOR = "moving_average"
LGBM = "lightgbm_global"


@dataclass
class SegmentInfo:
    """Scores and the decision for one segment (category and class) or one class."""

    key: str
    demand_class: str
    selected: str
    selected_stat: str
    reason: str
    n_products: int
    n_points: int
    valid: bool
    scores: dict[str, Metrics] = field(default_factory=dict)
    q_low: float = 0.0
    q_high: float = 0.0
    mean_level: float = 0.0

    def notes(self) -> dict[str, Any]:
        return {
            "demand_class": self.demand_class,
            "selected": self.selected,
            "selected_stat": self.selected_stat,
            "reason": self.reason,
            "n_products": self.n_products,
            "valid": self.valid,
            "q_low": self.q_low,
            "q_high": self.q_high,
            "mean_level": self.mean_level,
        }


@dataclass(frozen=True)
class ProductScore:
    method: str
    n_points: int
    mae: float
    rmse: float
    wape: float | None
    mean_actual: float
    coverage: float


@dataclass
class Selection:
    """The outcome of one backtest. It is what the light profile reuses."""

    segments: dict[str, SegmentInfo]
    classes: dict[str, SegmentInfo]
    products: dict[str, ProductScore]
    tenant: dict[str, Metrics]
    n_origins: int

    def resolve(
        self, key: str, demand_class: DemandClass, *, allow_lgbm: bool
    ) -> tuple[str, SegmentInfo | None]:
        """The method for a product of this segment, and the info used for its interval.

        A segment with too few products or points uses the class decision, then the moving
        average. Without the global model the best statistical method of the stored scores is
        used instead of a selected `lightgbm_global`.
        """
        seg = self.segments.get(key)
        info: SegmentInfo | None = seg if seg and seg.valid else self.classes.get(demand_class)
        if info is None or not info.valid:
            return ANCHOR, info
        method = info.selected if allow_lgbm else info.selected_stat
        return method, info


def choose(scores: Mapping[str, Metrics], candidates: Sequence[str]) -> tuple[str, str]:
    """Lowest MAE wins, unless it beats the moving average by less than 3 percent."""
    pool = {m: scores[m] for m in candidates if m in scores and scores[m].n_points > 0}
    if not pool:
        return ANCHOR, "default"
    winner = min(pool, key=lambda m: (pool[m].mae, m != ANCHOR, m))
    anchor = pool.get(ANCHOR)
    if winner == ANCHOR or anchor is None:
        return winner, "lowest_mae"
    gain = (anchor.mae - pool[winner].mae) / anchor.mae if anchor.mae > 0 else 0.0
    if gain < PARSIMONY:
        return ANCHOR, "parsimony"
    return winner, "lowest_mae"


def _residual_quantiles(a: np.ndarray, f: np.ndarray) -> tuple[float, float, float]:
    if a.size == 0:
        return 0.0, 0.0, 0.0
    resid = a - f
    return (
        float(np.quantile(resid, INTERVAL_LOWER_Q)),
        float(np.quantile(resid, INTERVAL_UPPER_Q)),
        float(f.mean()),
    )


def _score(
    data: BacktestData, members: Sequence[int], methods: Sequence[str], min_rank: int = 0
) -> dict[str, Metrics]:
    coverage = float(np.mean([data.coverage[p] for p in members])) if members else 0.0
    out: dict[str, Metrics] = {}
    for method in methods:
        a, f = pooled(data, members, method, min_rank)
        out[method] = compute_metrics(a, f, coverage)
    return out


def _decide(
    data: BacktestData, key: str, klass: str, members: Sequence[int], with_lgbm: bool
) -> SegmentInfo:
    stat_methods = STAT_CANDIDATES[klass]
    scores = _score(data, members, (*stat_methods, BASELINE_28, "seasonal_naive"))
    selected_stat, reason = choose(scores, stat_methods)
    n_points = scores[ANCHOR].n_points
    valid = len(members) >= MIN_SEGMENT_PRODUCTS and n_points >= MIN_SEGMENT_POINTS
    selected = selected_stat
    min_rank = 0
    if with_lgbm:
        # The global model is back tested on the newest origins only, so it is compared with
        # the statistical winner on those same origins.
        sub = data.n_origins - LGBM_BACKTEST_ORIGINS
        lg = _score(data, members, (LGBM,), sub)[LGBM]
        if lg.n_points > 0:
            scores[LGBM] = lg
            base = _score(data, members, (selected_stat,), sub)[selected_stat]
            if base.n_points > 0 and base.mae > 0 and lg.mae <= base.mae * (1 - PARSIMONY):
                selected, reason, min_rank = LGBM, "lowest_mae_global_model", sub
    a, f = pooled(data, members, selected, min_rank)
    q_low, q_high, mean_level = _residual_quantiles(a, f)
    return SegmentInfo(
        key=key,
        demand_class=klass,
        selected=selected,
        selected_stat=selected_stat,
        reason=reason,
        n_products=len(members),
        n_points=n_points,
        valid=valid,
        scores=scores,
        q_low=q_low,
        q_high=q_high,
        mean_level=mean_level,
    )


def select_methods(
    data: BacktestData,
    *,
    classes: Sequence[DemandClass],
    category_slugs: Sequence[str],
    product_keys: Sequence[str],
    with_lgbm: bool = False,
) -> Selection:
    """Score every segment and class, choose, and compute per product and tenant scores."""
    by_segment: dict[str, list[int]] = {}
    by_class: dict[str, list[int]] = {}
    for p, klass in enumerate(classes):
        if klass not in STAT_CANDIDATES:
            continue
        by_segment.setdefault(segment_key(category_slugs[p], klass), []).append(p)
        by_class.setdefault(klass, []).append(p)
    segments = {k: _decide(data, k, k.split("|")[1], m, with_lgbm) for k, m in by_segment.items()}
    class_infos = {k: _decide(data, f"class:{k}", k, m, with_lgbm) for k, m in by_class.items()}

    selection = Selection(segments, class_infos, {}, {}, data.n_origins)
    chosen: dict[int, str] = {}
    for p, klass in enumerate(classes):
        if klass not in STAT_CANDIDATES:
            continue
        key = segment_key(category_slugs[p], klass)
        method, _ = selection.resolve(key, klass, allow_lgbm=with_lgbm)
        chosen[p] = method
        sub = data.n_origins - LGBM_BACKTEST_ORIGINS if method == LGBM else 0
        m = product_metrics(data, p, method, sub)
        if m is not None:
            selection.products[product_keys[p]] = ProductScore(
                method, m.n_points, m.mae, m.rmse, m.wape, m.mean_actual, m.coverage
            )
    selection.tenant = tenant_scores(data, classes, chosen)
    return quantised(selection)


def quantised(selection: Selection) -> Selection:
    """Round every stored number the way `forecast_store` keeps it."""
    for info in [*selection.segments.values(), *selection.classes.values()]:
        info.scores = {m: sc.stored() for m, sc in info.scores.items()}
    selection.tenant = {k: m.stored() for k, m in selection.tenant.items()}
    selection.products = {
        k: ProductScore(
            p.method,
            p.n_points,
            round(p.mae, 4),
            round(p.rmse, 4),
            None if p.wape is None else round(p.wape, 4),
            round(p.mean_actual, 4),
            round(p.coverage, 3),
        )
        for k, p in selection.products.items()
    }
    return selection


def tenant_scores(
    data: BacktestData, classes: Sequence[DemandClass], chosen: Mapping[int, str]
) -> dict[str, Metrics]:
    """Pooled metrics of the chosen methods and the two baselines over the whole tenant.

    WAPE is pooled over smooth and erratic products only, where it means something. MAE and
    bias use every backtested product. Keys: `selected`, `moving_average_28`,
    `seasonal_naive`, and the same with a `_wape_scope` suffix for the WAPE scope.
    """
    out: dict[str, Metrics] = {}
    for scope, allowed in (("all", None), ("wape", ("smooth", "erratic"))):
        members = [p for p in chosen if allowed is None or classes[p] in allowed]
        coverage = float(np.mean([data.coverage[p] for p in members])) if members else 0.0
        a_parts: list[np.ndarray] = []
        f_parts: list[np.ndarray] = []
        for p in members:
            method = chosen[p]
            sub = data.n_origins - LGBM_BACKTEST_ORIGINS if method == LGBM else 0
            a, f = pooled(data, [p], method, sub)
            a_parts.append(a)
            f_parts.append(f)
        if a_parts:
            out[f"selected:{scope}"] = compute_metrics(
                np.concatenate(a_parts), np.concatenate(f_parts), coverage
            )
        for base in (BASELINE_28, "seasonal_naive"):
            a, f = pooled(data, members, base)
            out[f"{base}:{scope}"] = compute_metrics(a, f, coverage)
    return out


def sigma_for(
    product_key: str,
    selection: Selection,
    *,
    mean_level: float,
    category_key: str,
    demand_class: DemandClass,
    fallback_std: float,
) -> tuple[float, str]:
    """Daily forecast error scale for the safety stock (`engine-spec.md` 10.3).

    The product's own backtest RMSE when it has at least 14 points, else the segment RMSE
    scaled by the product mean over the segment mean, else the larger of the demand standard
    deviation and half the mean (flagged as assumed).
    """
    own = selection.products.get(product_key)
    if own is not None and own.n_points >= 14:
        return own.rmse, "product_backtest"
    info = selection.segments.get(segment_key(category_key, demand_class))
    info = info if info and info.valid else selection.classes.get(demand_class)
    if info is not None and info.valid:
        seg = info.scores.get(info.selected_stat)
        if seg is not None and seg.n_points > 0 and seg.mean_actual > 0:
            return seg.rmse * (mean_level / seg.mean_actual), "segment_backtest"
    return max(fallback_std, 0.5 * mean_level), "assumed"


def confidence_label(
    *,
    coverage: float,
    wape: float | None,
    mae_ratio: float | None,
    demand_class: DemandClass,
    censored_share: float,
    method: str,
    downgrades: int,
) -> Confidence:
    """High, medium or low from the evidence, then one level down per listed problem."""
    if demand_class in ("new", "no_history") or method == "category_prior":
        return "low"
    smooth = demand_class in ("smooth", "erratic")
    level = 0
    if (
        coverage >= HIGH_COVERAGE
        and smooth
        and wape is not None
        and wape <= HIGH_WAPE
        and censored_share <= CENSORED_SHARE_HIGH_CONFIDENCE
    ):
        level = 2
    elif coverage >= MEDIUM_COVERAGE and (
        (wape is not None and wape <= MEDIUM_WAPE)
        or (not smooth and mae_ratio is not None and mae_ratio <= INTERMITTENT_MAE_RATIO)
    ):
        level = 1
    level = max(level - downgrades, 0)
    labels: tuple[Confidence, Confidence, Confidence] = ("low", "medium", "high")
    return labels[level]


def interval(yhat: np.ndarray, info: SegmentInfo | None) -> tuple[np.ndarray, np.ndarray]:
    """80 percent interval from the segment residual quantiles, scaled by `yhat / mean level`."""
    if info is None or info.mean_level <= 0:
        return yhat.copy(), yhat.copy()
    scale = yhat / info.mean_level
    lower = np.maximum(yhat + info.q_low * scale, 0.0)
    upper = np.maximum(yhat + info.q_high * scale, yhat)
    return lower, upper
