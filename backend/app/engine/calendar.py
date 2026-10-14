"""Festival and season windows (`engine-spec.md` section 7, `india-calendar.md`)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.engine.types import BoolArray

WINDOWS = ("pre", "during", "post")


@dataclass(frozen=True)
class CalendarEvent:
    """One occurrence of an event. `event_key` groups the yearly occurrences."""

    slug: str
    event_key: str
    name: str
    kind: str
    start: date
    end: date
    pre_days: int
    post_days: int
    delay_days: int
    is_verified: bool = True
    affects_hours: bool = False

    def window(self, name: str) -> tuple[date, date] | None:
        """First and last day of the `pre`, `during` or `post` window, None when it is empty."""
        if name == "during":
            return (self.start, self.end)
        if name == "pre" and self.pre_days > 0:
            return (self.start - timedelta(days=self.pre_days), self.start - timedelta(days=1))
        if name == "post" and self.post_days > 0:
            return (self.end + timedelta(days=1), self.end + timedelta(days=self.post_days))
        return None

    @property
    def anchor(self) -> date:
        """First day of the occurrence including its pre window. Baselines end here."""
        return self.start - timedelta(days=self.pre_days)

    @property
    def last_day(self) -> date:
        return self.end + timedelta(days=self.post_days)

    def spans(self) -> list[tuple[str, date, date]]:
        out: list[tuple[str, date, date]] = []
        for name in WINDOWS:
            span = self.window(name)
            if span:
                out.append((name, span[0], span[1]))
        return out


def window_mask(
    events: Iterable[CalendarEvent], start: date, n_days: int, kinds: Sequence[str] = ("festival",)
) -> BoolArray:
    """Days that fall in any window of an event of the given kinds."""
    mask = np.zeros(n_days, dtype=np.bool_)
    for event in events:
        if event.kind not in kinds:
            continue
        for _name, lo, hi in event.spans():
            a = max((lo - start).days, 0)
            b = min((hi - start).days, n_days - 1)
            if b >= a:
                mask[a : b + 1] = True
    return mask


def upcoming(events: Iterable[CalendarEvent], as_of: date, days: int) -> list[CalendarEvent]:
    """Events whose pre window or main dates touch `[as_of, as_of + days]`, soonest first."""
    horizon = as_of + timedelta(days=days)
    hits = [e for e in events if e.kind != "season" and e.anchor <= horizon and e.last_day >= as_of]
    return sorted(hits, key=lambda e: (e.start, e.event_key))


def delivery_padding(events: Iterable[CalendarEvent], as_of: date, lead_days: int) -> int:
    """Extra delivery days from festivals whose `pre` or `during` window overlaps
    `[as_of, as_of + lead_days]` (`engine-spec.md` 7.4)."""
    last = as_of + timedelta(days=lead_days)
    padding = 0
    for event in events:
        if event.delay_days <= 0:
            continue
        for name in ("pre", "during"):
            span = event.window(name)
            if span and span[0] <= last and span[1] >= as_of:
                padding = max(padding, event.delay_days)
    return padding
