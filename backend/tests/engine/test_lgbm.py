"""The global model: features without lookahead, determinism, caps, lazy import, failures."""

import itertools
import subprocess
import sys
from datetime import date

import numpy as np
import pytest

from app.engine.calendar import CalendarEvent
from app.engine.features import FeatureBuilder, FeatureInputs, date_features, price_ratio_matrix
from app.engine.methods import lgbm
from app.engine.methods.lgbm import GlobalModelSkipped, origin_grid, run_global_model

START = date(2025, 6, 2)  # Monday
N_DAYS = 240
HORIZON = 14


def inputs(n_products: int = 10, n_days: int = N_DAYS, seed: int = 4) -> FeatureInputs:
    rng = np.random.default_rng(seed)
    shape = np.array([0.8, 0.9, 1.0, 1.0, 1.1, 1.4, 1.2])
    wd = (START.toordinal() - 1 + np.arange(n_days)) % 7
    level = rng.uniform(5, 30, (n_products, 1))
    y = rng.poisson(level * shape[wd]).astype(np.float64)
    events = [
        CalendarEvent(
            "fest-1", "fest", "Festival", "festival", date(2025, 9, 20), date(2025, 9, 24), 5, 2, 1
        ),
        CalendarEvent(
            "fest-2", "fest", "Festival", "festival", date(2026, 1, 20), date(2026, 1, 24), 5, 2, 1
        ),
    ]
    return FeatureInputs(
        y=y,
        start=START,
        category_codes=np.arange(n_products) % 3,
        promo=np.zeros((n_products, n_days + HORIZON), dtype=bool),
        price_ratio=np.ones((n_products, n_days)),
        events=events,
        horizon=HORIZON,
    )


def test_origin_grid_is_weekly_and_leaves_room_for_history() -> None:
    grid = origin_grid(300)
    assert grid[-1] == 293
    assert all(b - a == 7 for a, b in itertools.pairwise(grid))
    assert grid[0] >= 56
    assert origin_grid(40) == []


def test_features_have_the_documented_shape_and_names() -> None:
    fb = FeatureBuilder(inputs())
    tensor = fb.origin(200, HORIZON)
    assert tensor.shape == (10, HORIZON, len(fb.names))
    assert fb.names[:4] == ["lag_dow_1", "lag_dow_2", "lag_dow_3", "lag_dow_4"]
    assert fb.names[fb.category_index] == "category"
    assert fb.keys == ["fest"]
    assert fb.names[-3:] == ["fest_pre", "fest_during", "fest_post"]
    assert tensor[:, 0, fb.names.index("h")].tolist() == [1.0] * 10
    assert tensor[:, 5, fb.names.index("h")].tolist() == [6.0] * 10


def test_lags_are_the_latest_same_weekday_before_the_origin() -> None:
    inp = inputs()
    fb = FeatureBuilder(inp)
    o = 200  # a Monday-aligned origin? origin day index 200 -> weekday below
    tensor = fb.origin(o, HORIZON)
    for h in (1, 6, 8, 14):
        target = o + h - 1
        last_same = target - 7 * (-(-h // 7))
        assert last_same < o
        assert tensor[0, h - 1, 0] == inp.y[0, last_same]
        assert tensor[0, h - 1, 1] == inp.y[0, last_same - 7]


def test_features_never_read_days_from_the_origin_on() -> None:
    inp = inputs()
    fb = FeatureBuilder(inp)
    o = 180
    before = fb.origin(o, HORIZON).copy()
    noisy = inp.y.copy()
    noisy[:, o:] = np.random.default_rng(0).uniform(0, 999, noisy[:, o:].shape)
    changed = FeatureBuilder(
        FeatureInputs(
            y=noisy,
            start=inp.start,
            category_codes=inp.category_codes,
            promo=inp.promo,
            price_ratio=inp.price_ratio,
            events=inp.events,
            horizon=inp.horizon,
        )
    ).origin(o, HORIZON)
    assert np.array_equal(before, changed, equal_nan=True)


def test_labels_stop_at_the_limit() -> None:
    fb = FeatureBuilder(inputs())
    labels = fb.labels(200, HORIZON, 205)
    assert not np.isnan(labels[:, :5]).any()
    assert np.isnan(labels[:, 5:]).all()


def test_date_features_flag_the_event_windows() -> None:
    inp = inputs()
    calendar, flags, nxt = date_features(inp.events, START, 130)
    assert calendar[0].tolist() == [0.0, 2.0, 6.0, 23.0]
    day = (date(2025, 9, 16) - START).days  # four days before the start: inside the pre window
    assert flags[day].tolist() == [1.0, 0.0, 0.0]
    assert flags[(date(2025, 9, 22) - START).days].tolist() == [0.0, 1.0, 0.0]
    assert flags[(date(2025, 9, 25) - START).days].tolist() == [0.0, 0.0, 1.0]
    assert nxt[(date(2025, 9, 15) - START).days] == 5
    assert nxt[(date(2025, 9, 30) - START).days] == 60


def test_price_ratio_follows_a_discount() -> None:
    units = np.ones((1, 120))
    revenue = np.full((1, 120), 10.0)
    revenue[0, 100:] = 8.0
    ratio = price_ratio_matrix(units, revenue)
    assert ratio[0, 50] == pytest.approx(1.0)
    assert ratio[0, 110] < 0.95
    assert price_ratio_matrix(np.zeros((1, 10)), np.zeros((1, 10)))[0].tolist() == [1.0] * 10


def test_importing_the_methods_does_not_import_lightgbm() -> None:
    code = (
        "import sys, app.engine.methods, app.engine.forecast, app.engine.backtest;"
        "print('lightgbm' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    assert out.stdout.strip() == "False"


@pytest.fixture(scope="module")
def model_result() -> lgbm.GlobalModelResult:
    fb = FeatureBuilder(inputs())
    return run_global_model(fb, horizon=HORIZON, n_backtest_origins=2, n_rank_origins=12)


def test_global_model_outputs(model_result: lgbm.GlobalModelResult) -> None:
    res = model_result
    assert res.forecast.shape == (10, HORIZON)
    assert (res.forecast >= 0).all()
    assert res.objective in ("tweedie", "poisson")
    assert set(res.validation_mae) == {"tweedie", "poisson"}
    assert set(res.backtest) == {(p, r) for p in range(10) for r in (10, 11)}
    assert all(v.shape == (7,) and (v >= 0).all() for v in res.backtest.values())
    assert res.n_rows > 2000


def test_global_model_is_deterministic(model_result: lgbm.GlobalModelResult) -> None:
    again = run_global_model(
        FeatureBuilder(inputs()), horizon=HORIZON, n_backtest_origins=2, n_rank_origins=12
    )
    assert np.array_equal(again.forecast, model_result.forecast)
    assert again.objective == model_result.objective
    assert again.n_trees == model_result.n_trees


def test_global_model_learns_the_weekly_shape(model_result: lgbm.GlobalModelResult) -> None:
    wd = (START.toordinal() - 1 + N_DAYS + np.arange(HORIZON)) % 7
    saturday = model_result.forecast[:, wd == 5].mean()
    monday = model_result.forecast[:, wd == 0].mean()
    assert saturday > monday * 1.2


def test_too_little_history_is_skipped() -> None:
    fb = FeatureBuilder(inputs(n_days=90))
    with pytest.raises(GlobalModelSkipped):
        run_global_model(fb, horizon=HORIZON)


def test_the_time_cap_stops_the_model() -> None:
    fb = FeatureBuilder(inputs())
    with pytest.raises(GlobalModelSkipped, match="time cap"):
        run_global_model(fb, horizon=HORIZON, stop=lambda: True)


def test_row_cap_drops_older_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = FeatureBuilder(inputs())
    origins = origin_grid(N_DAYS)
    monkeypatch.setattr(lgbm, "LGBM_MAX_ROWS", 10 * HORIZON * 12)
    kept = lgbm._cap(origins, fb, HORIZON)
    assert len(kept) * 10 * HORIZON <= 10 * HORIZON * 12 or len(kept) <= lgbm.VALIDATION_ORIGINS + 4
    assert kept[-lgbm.VALIDATION_ORIGINS :] == origins[-lgbm.VALIDATION_ORIGINS :]
    assert len(kept) < len(origins)
