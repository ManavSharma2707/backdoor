"""IST helpers. Business dates are `date` in Asia/Kolkata, instants are aware UTC."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

from app.core.clock import IST

__all__ = [
    "IST",
    "data_cutoff_for_week",
    "date_range",
    "ist_date",
    "start_of_ist_day",
    "to_ist",
    "to_utc",
    "week_end",
    "week_start",
]


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Naive datetime is not allowed, attach a timezone first")
    return value


def to_utc(value: datetime) -> datetime:
    return _require_aware(value).astimezone(UTC)


def to_ist(value: datetime) -> datetime:
    return _require_aware(value).astimezone(IST)


def ist_date(value: datetime) -> date:
    """Business date of an instant."""
    return to_ist(value).date()


def start_of_ist_day(day: date) -> datetime:
    """Midnight IST of a business date, as an aware UTC instant."""
    return datetime.combine(day, time.min, tzinfo=IST).astimezone(UTC)


def week_start(day: date) -> date:
    """The Monday on or before `day`."""
    return day - timedelta(days=day.weekday())


def week_end(day: date) -> date:
    """The Sunday of the week that contains `day`."""
    return week_start(day) + timedelta(days=6)


def data_cutoff_for_week(monday: date) -> datetime:
    """Data cutoff of a plan week: Monday 00:00 IST as an aware UTC instant."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday.isoformat()} is not a Monday")
    return start_of_ist_day(monday)


def date_range(start: date, end: date) -> Iterator[date]:
    """Every date from `start` to `end`, both included."""
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)
