"""Forecast methods: known outputs, NaN handling, non negative, empty series, no lookahead."""

from datetime import date, timedelta

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engine.methods import STATISTICAL_METHODS, MethodContext
from app.engine.methods.croston import croston_rate
from app.engine.methods.ses import ses_level
from app.engine.types import Series

START = date(2026, 1, 5)  # Monday


def make(values: list[float]) -> Series:
    return Series(START, np.array(values, dtype=np.float64))


def horizon(series: Series, n: int = 7) -> list[date]:
    return [series.origin + timedelta(days=i) for i in range(n)]


def run(name: str, values: list[float], n: int = 7, ctx: MethodContext | None = None) -> np.ndarray:
    s = make(values)
    return STATISTICAL_METHODS[name](s, horizon(s, n), ctx or MethodContext()).yhat


WEEKLY = [10.0, 12.0, 14.0, 16.0, 18.0, 30.0, 24.0]  # Monday to Sunday


def test_seasonal_naive_repeats_last_week() -> None:
    values = WEEKLY * 8
    got = run("seasonal_naive", values, n=14)
    assert got.tolist() == WEEKLY * 2


def test_seasonal_naive_skips_a_censored_week() -> None:
    values = WEEKLY * 8
    values[-7:] = [float("nan")] * 7
    got = run("seasonal_naive", values)
    assert got.tolist() == WEEKLY  # two weeks back


def test_moving_average_uses_the_window_and_ignores_nan() -> None:
    values = [100.0] * 40 + [2.0, 4.0, float("nan"), 6.0] * 7
    got = run("moving_average", values)
    assert got == pytest.approx([4.0] * 7)  # last 28 days, six NaN-free values per 4 days
    intermittent = run("moving_average", values, ctx=MethodContext(demand_class="intermittent"))
    assert intermittent[0] == pytest.approx((100 * 28 + 4 * 21) / 49, rel=1e-6)


def test_moving_average_falls_back_to_older_days_when_the_window_is_empty() -> None:
    values = [5.0] * 20 + [float("nan")] * 30
    assert run("moving_average", values)[0] == pytest.approx(5.0)
    assert run("moving_average", [float("nan")] * 10).tolist() == [0.0] * 7


def test_weekday_profile_recovers_the_weekly_shape() -> None:
    got = run("weekday_profile", WEEKLY * 8)
    # Level 17.714; with eight observations per weekday the shrunk index is 1 + (raw - 1) * 8 / 12.
    level = sum(WEEKLY) / 7
    expected = [level * (1 + (v / level - 1) * 8 / 12) for v in WEEKLY]
    assert got == pytest.approx(expected)


def test_weekday_profile_needs_six_weeks() -> None:
    short = WEEKLY * 5  # 35 days
    got = run("weekday_profile", short)
    assert got == pytest.approx([sum(WEEKLY) / 7] * 7)


def test_ses_weekday_on_a_constant_weekly_pattern_equals_the_weekday_profile() -> None:
    got = run("ses_weekday", WEEKLY * 12)
    assert got == pytest.approx(run("weekday_profile", WEEKLY * 12), rel=1e-9)


def test_ses_level_does_not_depend_on_the_weekday_the_series_ends_on() -> None:
    mean_by_end = []
    for cut in range(7):
        values = (WEEKLY * 12)[: 84 - cut]
        mean_by_end.append(float(run("ses_weekday", values).mean()))
    assert max(mean_by_end) / min(mean_by_end) < 1.04


def test_ses_follows_a_level_shift() -> None:
    flat_then_up = [5.0] * 100 + [10.0] * 20
    got = run("ses_weekday", flat_then_up)
    assert 8.0 < got[0] <= 10.0


def test_ses_level_math_by_hand() -> None:
    level, err = ses_level([10.0, 20.0, 20.0], 0.5)
    assert level == pytest.approx(17.5)  # 10 -> 15 -> 17.5
    assert err == pytest.approx((10 + 5) / 2)


def test_croston_sba_by_hand() -> None:
    # Demand 4 after a gap of 3 days (interval 3), then 6 after a gap of 2 days (interval 2).
    y = [0, 0, 4, 0, 6, 0, 0]
    rate = croston_rate([float(v) for v in y], alpha=0.1)
    size = 4 + 0.1 * (6 - 4)
    interval = 3 + 0.1 * (2 - 3)
    assert rate == pytest.approx(0.95 * size / interval)
    assert croston_rate([0.0, 0.0, 0.0]) == 0.0


def test_croston_skips_nan_days() -> None:
    values = [0.0, float("nan"), 0.0, 4.0] + [0.0, 0.0, 5.0] * 12
    got = run("croston_sba", values)
    assert got[0] > 0
    assert got.tolist() == [got[0]] * 7


def test_category_prior_is_80_percent_of_the_category_mean() -> None:
    got = run("category_prior", [], ctx=MethodContext(category_mean=5.0))
    assert got == pytest.approx([4.0] * 7)
    assert run("category_prior", [], ctx=MethodContext()).tolist() == [0.0] * 7


@pytest.mark.parametrize("name", sorted(STATISTICAL_METHODS))
def test_empty_series_gives_zero_not_an_error(name: str) -> None:
    got = run(name, [])
    assert got.tolist() == [0.0] * 7


@pytest.mark.parametrize("name", sorted(STATISTICAL_METHODS))
def test_horizon_of_28_days_is_supported(name: str) -> None:
    got = run(name, WEEKLY * 10, n=28)
    assert got.shape == (28,)
    assert (got >= 0).all()


values_strategy = st.lists(
    st.one_of(st.floats(min_value=0, max_value=500), st.just(float("nan"))),
    min_size=0,
    max_size=140,
)


@settings(max_examples=60, deadline=None)
@given(values=values_strategy)
def test_no_method_returns_a_negative_or_nan_forecast(values: list[float]) -> None:
    for name in STATISTICAL_METHODS:
        got = run(name, values, n=28, ctx=MethodContext(category_mean=3.0))
        assert not np.isnan(got).any()
        assert (got >= 0).all()


def test_series_tail_and_origin() -> None:
    s = make([1.0, 2.0, 3.0, 4.0])
    assert s.origin == START + timedelta(days=4)
    tail = s.tail(2)
    assert tail.start == START + timedelta(days=2)
    assert tail.y.tolist() == [3.0, 4.0]
    assert s.tail(99).y.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert s.weekdays().tolist() == [0, 1, 2, 3]
