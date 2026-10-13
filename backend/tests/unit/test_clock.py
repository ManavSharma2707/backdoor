from datetime import UTC, date, datetime, timedelta

import pytest

from app.core import clock


def test_fake_clock_is_controllable() -> None:
    fake = clock.FakeClock(datetime(2026, 10, 12, 0, 30, tzinfo=UTC))
    with clock.use_clock(fake):
        assert clock.now_utc() == datetime(2026, 10, 12, 0, 30, tzinfo=UTC)
        fake.advance(timedelta(hours=1))
        assert clock.now_utc().hour == 1


def test_today_ist_follows_the_fake_clock() -> None:
    late_utc = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)  # already the 12th in Kolkata
    with clock.use_clock(clock.FakeClock(late_utc)):
        assert clock.today_ist() == date(2026, 10, 12)


def test_use_clock_restores_the_previous_clock() -> None:
    before = clock.get_clock()
    with clock.use_clock(clock.FakeClock(datetime(2026, 1, 1, tzinfo=UTC))):
        pass
    assert clock.get_clock() is before


def test_fake_clock_converts_to_utc() -> None:
    fake = clock.FakeClock(datetime(2026, 10, 12, 6, 0, tzinfo=clock.IST))
    assert fake.now() == datetime(2026, 10, 12, 0, 30, tzinfo=UTC)


def test_fake_clock_needs_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        clock.FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001
    fake = clock.FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="aware"):
        fake.set(datetime(2026, 1, 2))  # noqa: DTZ001


def test_system_clock_returns_aware_utc() -> None:
    now = clock.SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
