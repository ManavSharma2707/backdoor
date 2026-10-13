"""The only module that reads the system clock.

Everything else asks for `now_utc()` or `today_ist()`, or receives `as_of` from its caller.
Tests install a `FakeClock` with `use_clock`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controllable clock for tests."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs an aware datetime")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("FakeClock needs an aware datetime")
        self._now = value.astimezone(UTC)

    def advance(self, delta: timedelta) -> None:
        self._now += delta


_clock: Clock = SystemClock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    previous = _clock
    set_clock(clock)
    try:
        yield clock
    finally:
        set_clock(previous)


def now_utc() -> datetime:
    return _clock.now()


def today_ist() -> date:
    return _clock.now().astimezone(IST).date()
