"""Training matrices, effect matrices and forecasting of products with the selected methods."""

from datetime import date, timedelta

import numpy as np
import pytest

from app.engine.backtest import run_backtest
from app.engine.calendar import CalendarEvent
from app.engine.event_effects import EffectRecord, PromoOccurrence
from app.engine.forecast import (
    adjust_for_effects,
    category_means,
    censored_share,
    effect_matrices,
    fit_forecast,
    forecast_products,
    training_data,
)
from app.engine.methods import MethodContext
from app.engine.rollup import STATE_NAMES
from app.engine.selection import Selection, select_methods
from app.engine.types import DemandClass

START = date(2026, 1, 5)
CODE = {name: i for i, name in enumerate(STATE_NAMES)}


def codes(*rows: list[str]) -> np.ndarray:
    return np.array([[CODE[s] for s in row] for row in rows], dtype=np.int64)


def test_training_series_trusts_only_available_days_without_promotion() -> None:
    units = np.array([[3.0, 4.0, 0.0, 5.0, 2.0, 6.0]])
    states = codes(
        [
            "available",
            "sold_out_during_day",
            "stocked_out_all_day",
            "available",
            "not_launched",
            "unknown",
        ]
    )
    promo = np.array([[False, False, False, True, False, False]])
    td = training_data(units, states, promo, START)
    assert td.trusted[0, 0] == 3.0
    assert np.isnan(td.trusted[0, 1:]).all()  # censored, promotion, not launched, unknown
    assert td.with_promo[0, 3] == 5.0  # promotion days are kept for learning the promotion
    assert td.censored.tolist() == [[False, True, True, False, False, False]]
    assert td.n_days == 6


def test_returns_cannot_make_demand_negative() -> None:
    td = training_data(
        np.array([[-2.0, 1.0]]),
        codes(["available", "available"]),
        np.zeros((1, 2), dtype=bool),
        START,
    )
    assert td.trusted.tolist() == [[0.0, 1.0]]


def test_weekday_fill_replaces_censored_days_and_flags_them() -> None:
    n = 56
    units = np.full((1, n), 10.0)
    states = np.zeros((1, n), dtype=np.int64)
    states[0, 50] = CODE["stocked_out_all_day"]
    states[0, 51] = CODE["sold_out_during_day"]
    units[0, 50] = 0.0
    units[0, 51] = 4.0
    promo = np.zeros((1, n), dtype=bool)
    excluded = training_data(units, states, promo, START, "exclude")
    assert np.isnan(excluded.trusted[0, 50:52]).all()
    assert not excluded.fill_used.any()
    filled = training_data(units, states, promo, START, "weekday_fill")
    assert filled.trusted[0, 50] == pytest.approx(10.0)
    assert filled.trusted[0, 51] == pytest.approx(10.0)  # never below the estimate
    assert filled.fill_used[0, 50:52].tolist() == [True, True]
    assert filled.censored[0, 50]


def test_sold_out_day_keeps_actual_sales_when_they_exceed_the_estimate() -> None:
    n = 56
    units = np.full((1, n), 2.0)
    units[0, 51] = 9.0
    states = np.zeros((1, n), dtype=np.int64)
    states[0, 51] = CODE["sold_out_during_day"]
    filled = training_data(units, states, np.zeros((1, n), dtype=bool), START, "weekday_fill")
    assert filled.trusted[0, 51] == 9.0


def test_censored_share_of_the_last_eight_weeks() -> None:
    censored = np.zeros((2, 100), dtype=bool)
    censored[0, -28:] = True
    censored[1, :40] = True  # old, outside the window
    assert censored_share(censored).tolist() == [0.5, 0.0]


def test_category_means_use_only_eligible_products() -> None:
    trusted = np.array([[4.0] * 60, [2.0] * 60, [100.0] * 60, [np.nan] * 60])
    codes_ = np.array([0, 0, 0, 1])
    eligible = np.array([True, True, False, True])
    means = category_means(trusted, codes_, 3, eligible)
    assert means[0] == pytest.approx(3.0)
    assert np.isnan(means[1])
    assert np.isnan(means[2])


def test_adjusting_divides_the_effect_out() -> None:
    y = np.array([[10.0, 20.0, np.nan]])
    assert adjust_for_effects(y, np.array([[1.0, 2.0, 1.0]])).tolist()[0][:2] == [10.0, 10.0]


def record(key: str, window: str, mult: float, cat: str = "c0") -> EffectRecord:
    return EffectRecord(key, cat, window, mult, "learned", 1, 5, 0.9, {}, "medium", True)


def test_effect_matrices_share_category_timelines_and_give_products_their_own_promotions() -> None:
    event = CalendarEvent(
        "f",
        "f",
        "Festival",
        "festival",
        START + timedelta(days=10),
        START + timedelta(days=12),
        0,
        0,
        0,
    )
    promos = [PromoOccurrence(START + timedelta(days=3), START + timedelta(days=4), 1, None)]
    records = [record("f", "during", 1.5), record("promotion", "during", 1.4)]
    mult, keys = effect_matrices(
        records,
        [event],
        category_keys=["c0", "c1"],
        category_codes=np.array([0, 0, 1]),
        promotions=promos,
        start=START,
        n_days=15,
    )
    assert mult[0, 10:13].tolist() == [1.5, 1.5, 1.5]
    assert mult[2].tolist() == [1.0] * 15  # another category has no effect
    assert mult[1, 3:5].tolist() == [1.4, 1.4]  # the promotion belongs to product 1 only
    assert mult[0, 3:5].tolist() == [1.0, 1.0]
    assert keys[1][3] == "promotion"
    assert keys[0][10] == "f"


def test_fit_forecast_applies_the_horizon_multiplier() -> None:
    y = np.full(60, 10.0)
    dates = [START + timedelta(days=60 + i) for i in range(3)]
    plain = fit_forecast("moving_average", y, START, dates, MethodContext()).yhat
    scaled = fit_forecast(
        "moving_average", y, START, dates, MethodContext(), np.array([1.0, 2.0, 0.5])
    ).yhat
    assert plain.tolist() == [10.0] * 3
    assert scaled.tolist() == [10.0, 20.0, 5.0]


def selection_for(y: np.ndarray, classes: list[DemandClass]) -> Selection:
    n = y.shape[0]
    data = run_backtest(
        y_train=y,
        y_eval=y,
        multipliers=None,
        start=START,
        classes=classes,
        category_means=[None] * n,
    )
    return select_methods(
        data, classes=classes, category_slugs=["a"] * n, product_keys=[str(i) for i in range(n)]
    )


def test_forecast_products_resolves_methods_by_class() -> None:
    n_days, horizon = 160, 14
    rng = np.random.default_rng(2)
    y = rng.poisson(12.0, (6, n_days)).astype(np.float64)
    classes: list[DemandClass] = ["smooth"] * 4 + ["new", "no_history"]
    y[4, :-20] = np.nan  # a new product: 20 days of history
    y[5, :] = np.nan
    selection = selection_for(y[:4], classes[:4])
    # Pad the selection arrays: the backtest above only covered the four smooth products.
    mult = np.ones((6, n_days + horizon))
    mult[0, n_days + 2 : n_days + 4] = 2.0
    as_of = START + timedelta(days=n_days)
    out = forecast_products(
        y_adjusted=y,
        start=START,
        as_of=as_of,
        horizon=horizon,
        classes=classes,
        category_keys=["c0"],
        category_slugs=["a"] * 6,
        category_means=[None] * 5 + [6.0],
        selection=selection,
        multipliers=mult,
        event_keys=[[None] * (n_days + horizon)] * 6,
    )
    assert [f.method for f in out[4:]] == ["moving_average", "category_prior"]
    assert out[5].yhat.tolist() == [pytest.approx(4.8)] * horizon  # 0.8 of the category mean
    assert out[0].yhat[2] == pytest.approx(2.0 * out[0].base[2])
    assert out[1].yhat[2] == pytest.approx(out[1].base[2])
    assert all((f.yhat >= 0).all() for f in out)
    assert all((f.lower <= f.yhat + 1e-9).all() and (f.upper >= f.yhat - 1e-9).all() for f in out)
    assert out[0].segment == "a|smooth"
    assert out[5].segment is None


def test_global_forecast_is_used_unscaled_when_selected() -> None:
    n_days, horizon = 160, 7
    y = np.random.default_rng(2).poisson(12.0, (4, n_days)).astype(np.float64)
    selection = selection_for(y, ["smooth"] * 4)
    seg = selection.segments["a|smooth"]
    seg.selected = "lightgbm_global"
    mult = np.full((4, n_days + horizon), 2.0)
    common = {
        "y_adjusted": y,
        "start": START,
        "as_of": START + timedelta(days=n_days),
        "horizon": horizon,
        "classes": ["smooth"] * 4,
        "category_keys": ["c0"],
        "category_slugs": ["a"] * 4,
        "category_means": [None] * 4,
        "selection": selection,
        "multipliers": mult,
        "event_keys": [["x"] * (n_days + horizon)] * 4,
    }
    with_model = forecast_products(
        **common,
        global_forecast=np.full((4, horizon), 7.0),  # type: ignore[arg-type]
        allow_global=True,
    )
    assert with_model[0].method == "lightgbm_global"
    assert with_model[0].yhat.tolist() == [7.0] * horizon
    assert with_model[0].event_keys == [None] * horizon
    without = forecast_products(**common, allow_global=False)  # type: ignore[arg-type]
    assert without[0].method == seg.selected_stat
    assert without[0].multiplier.tolist() == [2.0] * horizon
    no_values = forecast_products(**common, global_forecast=None, allow_global=True)  # type: ignore[arg-type]
    assert no_values[0].method == seg.selected_stat
