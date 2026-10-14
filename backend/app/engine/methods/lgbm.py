"""The global gradient boosting model (`engine-spec.md` 5.3), one per tenant.

Full profile only. `lightgbm` is imported inside the functions, so the light profile and the API
never pay for it. Training is deterministic (one thread, fixed seed), capped in rows and in time,
and the caller falls back to the statistical ladder when anything here fails.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.engine.constants import (
    BACKTEST_ORIGINS,
    LGBM_BACKTEST_ORIGINS,
    LGBM_MAX_ROWS,
    LGBM_ORIGIN_WEEKS,
    LGBM_SEED,
)
from app.engine.features import FeatureBuilder
from app.engine.types import FloatArray

MIN_HISTORY_DAYS = 56
VALIDATION_ORIGINS = 6
EARLY_STOPPING_ROUNDS = 30
MIN_TRAIN_ROWS = 2000
OBJECTIVES = ("tweedie", "poisson")


class GlobalModelSkipped(RuntimeError):
    """Raised when the model cannot or should not run (too little data, time cap)."""


@dataclass
class GlobalModelResult:
    """Forecasts from the global model.

    `backtest[(product, rank)]` is the 7 day forecast made at origin number `rank` (the newest
    four ranks of the backtest). `forecast` has one row per product and one column per day of the
    horizon, for the plan date.
    """

    backtest: dict[tuple[int, int], FloatArray]
    forecast: FloatArray
    objective: str
    n_rows: int
    n_trees: int
    validation_mae: dict[str, float]


@dataclass
class _Rows:
    x: np.ndarray
    y: np.ndarray
    origin: np.ndarray


def _params(objective: str, n_estimators: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "objective": objective,
        "n_estimators": n_estimators,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_child_samples": 50,
        "colsample_bytree": 0.8,
        "subsample": 0.8,
        "subsample_freq": 1,
        "n_jobs": 1,
        "random_state": LGBM_SEED,
        "deterministic": True,
        "force_row_wise": True,
        "verbose": -1,
    }
    if objective == "tweedie":
        params["tweedie_variance_power"] = 1.2
    return params


def origin_grid(n_days: int, step: int = 7) -> list[int]:
    """Origin day indices, oldest first, one per week, newest `n_days` itself excluded."""
    newest = n_days - step
    oldest = max(MIN_HISTORY_DAYS, n_days - LGBM_ORIGIN_WEEKS * 7)
    return list(range(newest, oldest - 1, -step))[::-1]


def _collect(
    cache: dict[int, np.ndarray],
    builder: FeatureBuilder,
    origins: list[int],
    horizon: int,
    limit: int,
) -> _Rows:
    """Rows with a label before `limit`, for the given origins."""
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    os_: list[np.ndarray] = []
    for o in origins:
        feats = cache[o]
        labels = builder.labels(o, horizon, limit)
        ok = ~np.isnan(labels)
        xs.append(feats[ok])
        ys.append(labels[ok])
        os_.append(np.full(int(ok.sum()), o, dtype=np.int64))
    if not xs:
        return _Rows(np.zeros((0, len(builder.names)), dtype=np.float32), np.zeros(0), np.zeros(0))
    return _Rows(np.concatenate(xs), np.concatenate(ys), np.concatenate(os_))


def _cap(origins: list[int], builder: FeatureBuilder, horizon: int) -> list[int]:
    """Drop every other older origin until the rows fit the cap, keeping the newest ones."""
    per_origin = builder.n_products * horizon
    while len(origins) * per_origin > LGBM_MAX_ROWS and len(origins) > VALIDATION_ORIGINS + 4:
        keep = origins[-VALIDATION_ORIGINS:]
        older = origins[:-VALIDATION_ORIGINS][::2]
        origins = older + keep
    return origins


def run_global_model(
    builder: FeatureBuilder,
    *,
    horizon: int,
    n_backtest_origins: int = LGBM_BACKTEST_ORIGINS,
    n_rank_origins: int = BACKTEST_ORIGINS,
    stop: Callable[[], bool] | None = None,
) -> GlobalModelResult:
    """Train the model, back test it on the newest origins and forecast the plan horizon.

    The history ends at day index `T`. The plan date is `T`. Backtest origins are `T - 7`,
    `T - 14`, and so on. Each one is forecast by a model trained only on rows whose target day
    lies before that origin. The backtest forecasts are keyed by `(product, rank)` where rank 0
    is the oldest of `n_rank_origins` weekly origins and the newest is `n_rank_origins - 1`.
    """
    import lightgbm as lgb

    n_days = builder.inputs.n_days
    origins = origin_grid(n_days)
    if len(origins) < VALIDATION_ORIGINS + 4:
        raise GlobalModelSkipped("not enough history for the global model")
    origins = _cap(origins, builder, horizon)
    cache = {o: builder.origin(o, horizon) for o in [*origins, n_days]}
    cat = builder.category_index

    def should_stop() -> bool:
        return bool(stop and stop())

    def fit(limit: int, objective: str, n_trees: int | None) -> tuple[Any, float, int, int]:
        usable = [o for o in origins if o < limit]
        rows = _collect(cache, builder, usable, horizon, limit)
        if rows.x.shape[0] < MIN_TRAIN_ROWS:
            raise GlobalModelSkipped("not enough training rows")
        model = lgb.LGBMRegressor(**_params(objective, n_trees or 300))
        if n_trees is None:
            cut = sorted(set(usable))[-VALIDATION_ORIGINS]
            tr, va = rows.origin < cut, rows.origin >= cut
            model.fit(
                rows.x[tr],
                rows.y[tr],
                eval_X=(rows.x[va],),
                eval_y=(rows.y[va],),
                eval_metric="l1",
                categorical_feature=[cat],
                callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
            )
            best = model.best_score_["valid_0"]["l1"]
            return model, float(best), int(model.best_iteration_ or 300), int(rows.y.size)
        model.fit(rows.x, rows.y, categorical_feature=[cat])
        return model, 0.0, n_trees, int(rows.y.size)

    scores: dict[str, float] = {}
    models: dict[str, tuple[Any, int, int]] = {}
    for objective in OBJECTIVES:
        if should_stop():
            raise GlobalModelSkipped("time cap reached")
        model, score, trees, n_rows = fit(n_days, objective, None)
        scores[objective] = score
        models[objective] = (model, trees, n_rows)
    objective = min(scores, key=lambda k: (scores[k], k))
    final, trees, n_rows = models[objective]

    backtest: dict[tuple[int, int], FloatArray] = {}
    for j in range(1, n_backtest_origins + 1):
        if should_stop():
            raise GlobalModelSkipped("time cap reached")
        ob = n_days - 7 * j
        if ob not in cache:
            continue
        model, _, _, _ = fit(ob, objective, trees)
        pred = np.maximum(model.predict(cache[ob][:, :7, :].reshape(-1, cache[ob].shape[2])), 0.0)
        pred = pred.reshape(builder.n_products, 7)
        rank = n_rank_origins - j
        for p in range(builder.n_products):
            backtest[(p, rank)] = pred[p].astype(np.float64)

    if should_stop():
        raise GlobalModelSkipped("time cap reached")
    last = cache[n_days]
    pred = np.maximum(final.predict(last.reshape(-1, last.shape[2])), 0.0)
    forecast = pred.reshape(builder.n_products, horizon).astype(np.float64)
    return GlobalModelResult(backtest, forecast, objective, n_rows, trees, scores)
