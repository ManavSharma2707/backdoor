from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core import timeutil


class TestWeekStart:
    def test_monday_is_its_own_week_start(self) -> None:
        assert timeutil.week_start(date(2026, 10, 12)) == date(2026, 10, 12)

    @pytest.mark.parametrize(
        ("day", "monday"),
        [
            (date(2026, 10, 13), date(2026, 10, 12)),
            (date(2026, 10, 18), date(2026, 10, 12)),  # Sunday closes the week
            (date(2026, 10, 11), date(2026, 10, 5)),
            (date(2027, 1, 1), date(2026, 12, 28)),  # across a year boundary
        ],
    )
    def test_any_day_maps_to_the_monday_before(self, day: date, monday: date) -> None:
        assert timeutil.week_start(day) == monday

    def test_week_end_is_sunday(self) -> None:
        assert timeutil.week_end(date(2026, 10, 14)) == date(2026, 10, 18)

    @given(st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 1, 1)))
    def test_week_start_properties(self, day: date) -> None:
        monday = timeutil.week_start(day)
        assert monday.weekday() == 0
        assert 0 <= (day - monday).days <= 6
        assert timeutil.week_end(day) - monday == timedelta(days=6)


class TestIst:
    def test_ist_is_five_thirty_ahead(self) -> None:
        instant = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
        local = timeutil.to_ist(instant)
        assert (local.hour, local.minute) == (5, 30)

    def test_business_date_rolls_over_at_ist_midnight(self) -> None:
        before = datetime(2026, 10, 11, 18, 29, tzinfo=UTC)  # 23:59 IST on the 11th
        after = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)  # 00:00 IST on the 12th
        assert timeutil.ist_date(before) == date(2026, 10, 11)
        assert timeutil.ist_date(after) == date(2026, 10, 12)

    def test_start_of_ist_day_is_utc(self) -> None:
        start = timeutil.start_of_ist_day(date(2026, 10, 12))
        assert start == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
        assert start.utcoffset() == timedelta(0)

    def test_data_cutoff_is_monday_midnight_ist(self) -> None:
        cutoff = timeutil.data_cutoff_for_week(date(2026, 10, 12))
        assert timeutil.to_ist(cutoff) == datetime(2026, 10, 12, 0, 0, tzinfo=timeutil.IST)

    def test_data_cutoff_rejects_non_monday(self) -> None:
        with pytest.raises(ValueError, match="not a Monday"):
            timeutil.data_cutoff_for_week(date(2026, 10, 13))

    def test_naive_datetimes_are_refused(self) -> None:
        with pytest.raises(ValueError, match="Naive"):
            timeutil.to_ist(datetime(2026, 10, 12, 0, 0))  # noqa: DTZ001
        with pytest.raises(ValueError, match="Naive"):
            timeutil.to_utc(datetime(2026, 10, 12, 0, 0))  # noqa: DTZ001


def test_date_range_includes_both_ends() -> None:
    days = list(timeutil.date_range(date(2026, 10, 10), date(2026, 10, 12)))
    assert days == [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)]
    assert list(timeutil.date_range(date(2026, 10, 12), date(2026, 10, 11))) == []
