"""Rolling origin backtest, metrics, selection with the parsimony rule, confidence labels."""

import itertools
from datetime import date

import numpy as np
import pytest

from app.engine.backtest import (
    BASELINE_28,
    compute_metrics,
    origin_dates,
    pooled,
    run_backtest,
)
from app.engine.selection import (
    ANCHOR,
    Metrics,
    choose,
    confidence_label,
    interval,
    select_methods,
    sigma_for,
)
from app.engine.types import DemandClass

START = date(2026, 1, 5)
N_DAYS = 200


def weekly_series(n_products: int = 4, *, seed: int = 3, level: float = 20.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shape = np.array([0.8, 0.9, 1.0, 1.0, 1.1, 1.3, 1.1])
    wd = (START.toordinal() - 1 + np.arange(N_DAYS)) % 7
    return rng.poisson(np.outer(np.full(n_products, level), shape[wd])).astype(np.float64)


def backtest(y: np.ndarray, classes: list[DemandClass] | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    n = y.shape[0]
    return run_backtest(
        y_train=y,
        y_eval=y,
        multipliers=None,
        start=START,
        classes=classes or ["smooth"] * n,
        category_means=[None] * n,
        **kwargs,  # type: ignore[arg-type]
    )


def test_metrics_by_hand() -> None:
    a = np.array([10.0, 20.0, 0.0, 30.0])
    f = np.array([12.0, 18.0, 3.0, 30.0])
    m = compute_metrics(a, f, 0.9)
    assert m.n_points == 4
    assert m.mae == pytest.approx((2 + 2 + 3 + 0) / 4)
    assert m.rmse == pytest.approx(np.sqrt((4 + 4 + 9 + 0) / 4))
    assert m.wape == pytest.approx(7 / 60)
    assert m.bias == pytest.approx((2 - 2 + 3 + 0) / 60)
    assert m.mean_actual == 15.0
    assert m.mae_ratio == pytest.approx(7 / 4 / 15)
    assert m.coverage == 0.9


def test_wape_and_bias_are_none_when_nothing_sold() -> None:
    m = compute_metrics(np.zeros(5), np.ones(5), 1.0)
    assert m.wape is None
    assert m.bias is None
    assert m.mae == 1.0
    assert compute_metrics(np.zeros(0), np.zeros(0), 1.0).n_points == 0


def test_origins_are_weekly_and_end_a_week_before_the_plan() -> None:
    got = origin_dates(date(2026, 10, 12), 12)
    assert len(got) == 12
    assert got[-1] == date(2026, 10, 5)
    assert got[0] == date(2026, 7, 20)
    assert all((b - a).days == 7 for a, b in itertools.pairwise(got))


def test_backtest_scores_every_candidate_on_the_same_points() -> None:
    data = backtest(weekly_series())
    for p in range(4):
        sets = data.errors[p]
        assert {
            "moving_average",
            "weekday_profile",
            "ses_weekday",
            "seasonal_naive",
            BASELINE_28,
        } <= set(sets)
        assert "croston_sba" not in sets  # smooth products do not get Croston
        sizes = {len(es.actual) for es in sets.values()}
        assert sizes == {12 * 7}
    assert all(c == 1.0 for c in data.coverage)


def test_intermittent_candidates() -> None:
    y = (np.random.default_rng(1).random((3, N_DAYS)) < 0.2).astype(np.float64) * 3
    data = backtest(y, ["intermittent"] * 3)
    assert {"moving_average", "croston_sba", "weekday_profile"} <= set(data.errors[0])
    assert "ses_weekday" not in data.errors[0]


def test_untrusted_target_days_are_left_out_and_lower_coverage() -> None:
    y = weekly_series(2)
    y[0, -30:-20] = np.nan
    data = backtest(y)
    assert len(data.errors[0]["moving_average"].actual) == 12 * 7 - 10
    assert data.coverage[0] == pytest.approx((12 * 7 - 10) / (12 * 7))
    assert data.coverage[1] == 1.0


def test_new_products_are_not_backtested() -> None:
    data = backtest(weekly_series(2), ["new", "smooth"])
    assert data.errors[0] == {}
    assert data.coverage[0] == 0.0


def test_no_lookahead_future_noise_does_not_change_earlier_origins() -> None:
    """The forecast at origin k may only depend on the days before it."""
    y = weekly_series(3)
    clean = backtest(y)
    k = 6  # origin number 6 starts a week 6 of 12
    o = (clean.origins[k] - START).days
    noisy_train = y.copy()
    noisy_train[:, o:] = np.random.default_rng(99).uniform(0, 500, noisy_train[:, o:].shape)
    noisy = run_backtest(
        y_train=noisy_train,
        y_eval=y,
        multipliers=None,
        start=START,
        classes=["smooth"] * 3,
        category_means=[None] * 3,
    )
    for p in range(3):
        for method, es in clean.errors[p].items():
            other = noisy.errors[p][method]
            early = [i for i, r in enumerate(es.rank) if r <= k]
            late = [i for i, r in enumerate(es.rank) if r > k]
            assert [es.forecast[i] for i in early] == [other.forecast[i] for i in early], method
            assert [es.forecast[i] for i in late] != [other.forecast[i] for i in late], method


def test_effect_multipliers_scale_the_forecast_and_are_not_applied_to_the_baseline_series() -> None:
    y = np.full((1, N_DAYS), 10.0)
    mult = np.ones((1, N_DAYS + 28))
    mult[0, N_DAYS - 7 : N_DAYS] = 2.0
    data = run_backtest(
        y_train=y,
        y_eval=y,
        multipliers=mult,
        start=START,
        classes=["smooth"],
        category_means=[None],
        n_origins=2,
    )
    last = [
        f
        for f, r in zip(
            data.errors[0]["moving_average"].forecast,
            data.errors[0]["moving_average"].rank,
            strict=True,
        )
        if r == 1
    ]
    assert last == [20.0] * 7


def test_extra_forecasts_enter_the_error_sets() -> None:
    y = weekly_series(2)
    extra = {"lightgbm_global": {(0, 11): np.full(7, 5.0), (0, 10): np.full(7, 5.0)}}
    data = backtest(y, extra=extra)
    es = data.errors[0]["lightgbm_global"]
    assert set(es.rank) == {10, 11}
    assert "lightgbm_global" in data.errors[1]  # present but empty for product 1
    assert data.errors[1]["lightgbm_global"].actual == []
    a, f = pooled(data, [0], "lightgbm_global", min_rank=11)
    assert a.size == 7
    assert f.tolist() == [5.0] * 7


def metrics(mae: float, n: int = 400) -> Metrics:
    return Metrics(n, mae, mae * 1.3, 0.4, 0.0, 10.0, 0.9)


def test_parsimony_keeps_the_moving_average_unless_the_gain_is_three_percent() -> None:
    cands = ("seasonal_naive", "moving_average", "weekday_profile", "ses_weekday")
    scores = {
        "seasonal_naive": metrics(3.0),
        "moving_average": metrics(2.00),
        "weekday_profile": metrics(1.95),
        "ses_weekday": metrics(1.97),
    }
    assert choose(scores, cands) == (ANCHOR, "parsimony")  # 2.5 percent better is not enough
    scores["weekday_profile"] = metrics(1.93)  # 3.5 percent better
    assert choose(scores, cands) == ("weekday_profile", "lowest_mae")
    scores["weekday_profile"] = metrics(2.2)
    scores["ses_weekday"] = metrics(2.1)
    assert choose(scores, cands) == (ANCHOR, "lowest_mae")  # the anchor is simply best


def test_choose_without_scores_defaults_to_the_anchor() -> None:
    assert choose({}, ("moving_average",)) == (ANCHOR, "default")
    assert choose({"moving_average": metrics(1.0, 0)}, ("moving_average",)) == (ANCHOR, "default")


def test_selection_over_a_noise_only_tenant_keeps_the_moving_average() -> None:
    rng = np.random.default_rng(5)
    y = rng.poisson(8.0, (6, N_DAYS)).astype(np.float64)
    data = backtest(y)
    sel = select_methods(
        data,
        classes=["smooth"] * 6,
        category_slugs=["a"] * 6,
        product_keys=[str(i) for i in range(6)],
    )
    seg = sel.segments["a|smooth"]
    assert seg.valid
    assert seg.selected == ANCHOR


def test_selection_finds_a_real_weekday_pattern() -> None:
    y = weekly_series(6, level=30.0)
    data = backtest(y)
    sel = select_methods(
        data,
        classes=["smooth"] * 6,
        category_slugs=["a"] * 6,
        product_keys=[str(i) for i in range(6)],
    )
    seg = sel.segments["a|smooth"]
    assert seg.selected in ("weekday_profile", "ses_weekday")
    assert seg.reason == "lowest_mae"
    assert sel.products["0"].method == seg.selected
    assert sel.tenant["selected:all"].mae < sel.tenant[f"{BASELINE_28}:all"].mae


def test_small_segments_use_the_class_decision() -> None:
    y = weekly_series(7, level=30.0)
    data = backtest(y)
    slugs = ["a"] * 5 + ["b", "b"]
    sel = select_methods(
        data, classes=["smooth"] * 7, category_slugs=slugs, product_keys=[str(i) for i in range(7)]
    )
    assert sel.segments["a|smooth"].valid
    assert not sel.segments["b|smooth"].valid
    method, info = sel.resolve("b|smooth", "smooth", allow_lgbm=False)
    assert info is sel.classes["smooth"]
    assert method == sel.classes["smooth"].selected
    assert sel.resolve("c|smooth", "smooth", allow_lgbm=False)[1] is sel.classes["smooth"]
    unseen, none_info = sel.resolve("x|lumpy", "lumpy", allow_lgbm=False)
    assert (unseen, none_info) == (ANCHOR, None)


def test_global_model_is_dropped_without_permission() -> None:
    y = weekly_series(6, level=30.0)
    data = backtest(
        y,
        extra={
            "lightgbm_global": {(p, r): np.full(7, 30.0) for p in range(6) for r in range(8, 12)}
        },
    )
    sel = select_methods(
        data,
        classes=["smooth"] * 6,
        category_slugs=["a"] * 6,
        product_keys=[str(i) for i in range(6)],
        with_lgbm=True,
    )
    seg = sel.segments["a|smooth"]
    assert "lightgbm_global" in seg.scores
    seg.selected = "lightgbm_global"  # pretend it won
    assert sel.resolve("a|smooth", "smooth", allow_lgbm=True)[0] == "lightgbm_global"
    assert sel.resolve("a|smooth", "smooth", allow_lgbm=False)[0] == seg.selected_stat


def test_sigma_falls_back_in_three_steps() -> None:
    y = weekly_series(6)
    data = backtest(y)
    keys = [str(i) for i in range(6)]
    sel = select_methods(data, classes=["smooth"] * 6, category_slugs=["a"] * 6, product_keys=keys)
    own = sigma_for(
        "0", sel, mean_level=20.0, category_key="a", demand_class="smooth", fallback_std=1.0
    )
    assert own[1] == "product_backtest"
    assert own[0] == pytest.approx(sel.products["0"].rmse)
    seg = sigma_for(
        "missing", sel, mean_level=40.0, category_key="a", demand_class="smooth", fallback_std=1.0
    )
    assert seg[1] == "segment_backtest"
    assert seg[0] > own[0]  # a product that sells twice as much has a larger error scale
    assumed = sigma_for(
        "missing", sel, mean_level=10.0, category_key="zz", demand_class="lumpy", fallback_std=2.0
    )
    assert assumed == (5.0, "assumed")  # half the mean beats a standard deviation of 2


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "high"),
        ({"coverage": 0.79}, "medium"),
        ({"wape": 0.36}, "medium"),
        ({"censored_share": 0.16}, "medium"),
        ({"coverage": 0.59}, "low"),
        ({"wape": 0.61}, "low"),
        ({"wape": None}, "low"),
        ({"demand_class": "intermittent", "wape": 1.2, "mae_ratio": 0.9}, "medium"),
        ({"demand_class": "intermittent", "wape": 1.2, "mae_ratio": 1.1}, "low"),
        ({"demand_class": "new"}, "low"),
        ({"method": "category_prior"}, "low"),
        ({"downgrades": 1}, "medium"),
        ({"downgrades": 2}, "low"),
        ({"downgrades": 5}, "low"),
    ],
)
def test_confidence_boundaries(kwargs: dict[str, object], expected: str) -> None:
    base: dict[str, object] = {
        "coverage": 0.85,
        "wape": 0.30,
        "mae_ratio": None,
        "demand_class": "smooth",
        "censored_share": 0.0,
        "method": "weekday_profile",
        "downgrades": 0,
    }
    assert confidence_label(**{**base, **kwargs}) == expected  # type: ignore[arg-type]


def test_interval_scales_with_the_forecast_and_stays_non_negative() -> None:
    y = weekly_series(6)
    data = backtest(y)
    sel = select_methods(
        data,
        classes=["smooth"] * 6,
        category_slugs=["a"] * 6,
        product_keys=[str(i) for i in range(6)],
    )
    info = sel.segments["a|smooth"]
    yhat = np.array([0.0, 5.0, 20.0, 40.0])
    low, high = interval(yhat, info)
    assert (low >= 0).all()
    assert (high >= yhat).all()
    assert (low <= yhat).all()
    assert high[3] - low[3] == pytest.approx(2 * (high[2] - low[2]), rel=1e-6)
    flat_low, flat_high = interval(yhat, None)
    assert flat_low.tolist() == flat_high.tolist() == yhat.tolist()
