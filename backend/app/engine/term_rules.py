"""Effective dated supplier terms: overlap checks and superseding. Pure functions.

Two terms for the same supplier and product, or two primary terms for one product, may not be
in force on the same day. The one exception is the normal way to change a price: a new open
ended term that starts after an open ended one closes it the day before.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Span:
    """A term's identity and the days it is in force. `end=None` means still in force."""

    key: Hashable
    start: date
    end: date | None


@dataclass(frozen=True)
class TermPlan:
    """What adding a new span means for the existing ones."""

    close: tuple[tuple[Hashable, date], ...] = ()
    conflicts: tuple[Hashable, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.conflicts


def overlaps(a_start: date, a_end: date | None, b_start: date, b_end: date | None) -> bool:
    """True when the two inclusive ranges share a day."""
    return (a_end is None or a_end >= b_start) and (b_end is None or b_end >= a_start)


def plan_new_span(existing: Sequence[Span], start: date, end: date | None) -> TermPlan:
    """Decide what to do with `existing` when a span `start..end` is added.

    Overlapping spans conflict, except an earlier open ended span when the new one is also
    open ended: that one is closed on the day before `start`.
    """
    if end is not None and end < start:
        raise ValueError("A term cannot end before it starts")
    close: list[tuple[Hashable, date]] = []
    conflicts: list[Hashable] = []
    for span in existing:
        if not overlaps(span.start, span.end, start, end):
            continue
        if end is None and span.end is None and span.start < start:
            close.append((span.key, start - timedelta(days=1)))
        else:
            conflicts.append(span.key)
    return TermPlan(close=tuple(close), conflicts=tuple(conflicts))
