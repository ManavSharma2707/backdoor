"""Demand classification on constructed series for each class."""

import numpy as np

from app.engine.demand_class import classify_demand, segment_key


def series(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=np.float64)


def test_smooth_series() -> None:
    y = series([5, 6, 5, 7, 6, 5] * 10)
    profile = classify_demand(y)
    assert profile.demand_class == "smooth"
    assert profile.adi == 1.0
    assert profile.cv2 is not None and profile.cv2 < 0.49


def test_erratic_series_has_demand_every_day_but_wild_sizes() -> None:
    y = series([1, 20, 2, 25, 1, 30] * 10)
    assert classify_demand(y).demand_class == "erratic"


def test_intermittent_series_has_gaps_and_steady_sizes() -> None:
    y = series([4, 0, 0, 5, 0, 0, 0] * 10)
    profile = classify_demand(y)
    assert profile.demand_class == "intermittent"
    assert profile.adi is not None and profile.adi > 1.32


def test_lumpy_series_has_gaps_and_wild_sizes() -> None:
    y = series([1, 0, 0, 0, 30, 0, 0, 0, 2, 0, 0, 0, 40, 0] * 6)
    assert classify_demand(y).demand_class == "lumpy"


def test_few_trusted_days_make_a_new_product() -> None:
    y = series([np.nan] * 100 + [3] * 20)
    assert classify_demand(y).demand_class == "new"


def test_almost_no_history() -> None:
    assert classify_demand(series([np.nan] * 90 + [2, 3, 1])).demand_class == "no_history"
    assert classify_demand(series([])).demand_class == "no_history"


def test_only_trusted_days_count_and_all_zero_is_intermittent() -> None:
    y = series([np.nan, 0.0] * 40)
    profile = classify_demand(y)
    assert profile.trusted_days == 40
    assert profile.demand_class == "intermittent"
    assert profile.mean_daily == 0.0


def test_only_the_last_180_days_are_used() -> None:
    y = series([9, 0, 0, 0, 0, 0, 0, 0] * 50 + [5] * 180)
    assert classify_demand(y).demand_class == "smooth"


def test_segment_key() -> None:
    assert segment_key("biscuits", "smooth") == "biscuits|smooth"
