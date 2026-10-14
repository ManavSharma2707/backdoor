"""Global reference rows: GST slabs and the India festival and season calendar.

Source of truth is `context/india-calendar.md`. Festival dates are best known values and stay
`is_verified = false` until checked against two sources (Prompt 3). Seasons are conventions,
not moon dependent dates, so they are stored as verified.

`upsert_reference_data` is idempotent. A re-run never turns a verified row back into an
unverified one, never touches rows the owner created, and never changes `is_active`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.reference import CalendarEvent, TaxRate

log = get_logger(__name__)

OWNER_NOTE = "owner"
GST_EFFECTIVE_FROM = date(2025, 9, 22)
GST_NOTE = "Representative mapping only. This is not tax advice."

TAX_RATES: tuple[tuple[str, str, str], ...] = (
    ("GST0", "0.00", "GST 0%"),
    ("GST5", "5.00", "GST 5%"),
    ("GST18", "18.00", "GST 18%"),
    ("GST40", "40.00", "GST 40%"),
)

NOTE_SEASON = "Seasonal window, a convention rather than a dated festival."
NOTE_APPROX = "Approximate date for forecasts beyond 2026. Always unverified."
NOTE_FIXED = "Fixed calendar dates, 24 Dec to 1 Jan. The window length is a design choice."
CHECKED = "Checked 14 Oct 2026 against two independent sources."


@dataclass(frozen=True)
class EventRow:
    event_key: str
    name: str
    kind: str
    start: date
    end: date
    pre: int
    post: int
    delay: int
    note: str
    affects_hours: bool = False
    checked: bool = False

    @property
    def slug(self) -> str:
        return f"{self.event_key}-{self.start.year}"

    @property
    def verified(self) -> bool:
        return self.kind == "season" or self.checked


def _festival(
    key: str,
    name: str,
    start: str,
    end: str,
    pre: int,
    post: int,
    delay: int,
    note: str,
    checked: bool = True,
) -> EventRow:
    return EventRow(
        key,
        name,
        "festival",
        date.fromisoformat(start),
        date.fromisoformat(end),
        pre,
        post,
        delay,
        note,
        affects_hours=key in {"diwali", "holi"},
        checked=checked,
    )


def _season(key: str, name: str, start: str, end: str) -> EventRow:
    return EventRow(
        key,
        name,
        "season",
        date.fromisoformat(start),
        date.fromisoformat(end),
        0,
        0,
        0,
        NOTE_SEASON,
    )


CALENDAR_EVENTS: tuple[EventRow, ...] = (
    # 2025, inside the simulated history that starts on 14 Apr 2025.
    _season("summer", "Summer", "2025-03-01", "2025-05-31"),
    _festival(
        "eid_adha",
        "Bakri Eid",
        "2025-06-07",
        "2025-06-07",
        3,
        1,
        0,
        f"{CHECKED} 7 Jun 2025 in India, a day earlier elsewhere (moon dependent).",
    ),
    _season("monsoon", "Monsoon", "2025-06-10", "2025-09-30"),
    _festival(
        "raksha_bandhan",
        "Raksha Bandhan",
        "2025-08-09",
        "2025-08-09",
        7,
        2,
        0,
        f"{CHECKED} 9 Aug 2025.",
    ),
    _festival(
        "ganesh_chaturthi",
        "Ganesh Chaturthi",
        "2025-08-27",
        "2025-09-06",
        10,
        3,
        1,
        f"{CHECKED} Chaturthi 27 Aug, Anant Chaturdashi 6 Sep 2025. One source was a day earlier.",
    ),
    _festival(
        "navratri_dussehra",
        "Navratri and Dussehra",
        "2025-09-22",
        "2025-10-02",
        5,
        2,
        1,
        f"{CHECKED} 22 Sep to 2 Oct 2025, Dussehra on 2 Oct.",
    ),
    _festival(
        "diwali",
        "Diwali",
        "2025-10-18",
        "2025-10-23",
        14,
        4,
        2,
        f"{CHECKED} Dhanteras 18 Oct, Lakshmi Puja 20 Oct (one source said 21 Oct), "
        "Bhai Dooj 23 Oct 2025. The window spans all of it.",
    ),
    _season("winter", "Winter", "2025-11-15", "2026-02-15"),
    _festival(
        "christmas_ny", "Christmas and New Year", "2025-12-24", "2026-01-01", 7, 2, 0, NOTE_FIXED
    ),
    # 2026
    _festival(
        "makar_sankranti",
        "Makar Sankranti",
        "2026-01-14",
        "2026-01-14",
        5,
        1,
        0,
        f"{CHECKED} 14 Jan 2026.",
    ),
    _festival(
        "holi",
        "Holi",
        "2026-03-03",
        "2026-03-04",
        5,
        2,
        0,
        f"{CHECKED} Holika Dahan 3 Mar, colour day 4 Mar 2026. The window covers both days.",
    ),
    _festival(
        "gudi_padwa",
        "Gudi Padwa",
        "2026-03-19",
        "2026-03-20",
        5,
        2,
        0,
        f"{CHECKED} 19 Mar 2026 in most sources, a state holiday list says 20 Mar. "
        "The window covers both days.",
    ),
    _festival(
        "eid_fitr",
        "Eid al-Fitr",
        "2026-03-21",
        "2026-03-21",
        7,
        2,
        0,
        f"{CHECKED} 21 Mar 2026 in India after the moon was not sighted on 19 Mar. "
        "A day earlier in some countries.",
    ),
    _season("summer", "Summer", "2026-03-01", "2026-05-31"),
    _festival(
        "eid_adha",
        "Bakri Eid",
        "2026-05-28",
        "2026-05-28",
        3,
        1,
        0,
        f"{CHECKED} 28 May 2026 in most of India, 27 May in one region.",
    ),
    _season("monsoon", "Monsoon", "2026-06-10", "2026-09-30"),
    _festival(
        "raksha_bandhan",
        "Raksha Bandhan",
        "2026-08-28",
        "2026-08-28",
        7,
        2,
        0,
        f"{CHECKED} 28 Aug 2026.",
    ),
    _festival(
        "ganesh_chaturthi",
        "Ganesh Chaturthi",
        "2026-09-14",
        "2026-09-25",
        10,
        3,
        1,
        f"{CHECKED} Chaturthi 14 Sep 2026. Anant Chaturdashi 25 Sep, one source said 24 Sep.",
    ),
    _festival(
        "navratri_dussehra",
        "Navratri and Dussehra",
        "2026-10-11",
        "2026-10-21",
        5,
        2,
        1,
        f"{CHECKED} Starts 11 Oct, Dussehra 20 Oct 2026. One source says 12 Oct and 21 Oct, "
        "so the window runs to 21 Oct.",
    ),
    _festival(
        "diwali",
        "Diwali",
        "2026-11-06",
        "2026-11-10",
        14,
        4,
        2,
        f"{CHECKED} Dhanteras 6 Nov, Lakshmi Puja 8 Nov, Bhai Dooj 10 Nov 2026.",
    ),
    _season("winter", "Winter", "2026-11-15", "2027-02-15"),
    _festival(
        "christmas_ny", "Christmas and New Year", "2026-12-24", "2027-01-01", 7, 2, 0, NOTE_FIXED
    ),
    # 2027, approximate, always unverified.
    _festival(
        "makar_sankranti",
        "Makar Sankranti",
        "2027-01-14",
        "2027-01-14",
        5,
        1,
        0,
        NOTE_APPROX,
        checked=False,
    ),
    _festival(
        "eid_fitr", "Eid al-Fitr", "2027-03-10", "2027-03-10", 7, 2, 0, NOTE_APPROX, checked=False
    ),
    _festival("holi", "Holi", "2027-03-22", "2027-03-22", 5, 2, 0, NOTE_APPROX, checked=False),
    _festival(
        "gudi_padwa", "Gudi Padwa", "2027-04-07", "2027-04-07", 5, 2, 0, NOTE_APPROX, checked=False
    ),
    _festival(
        "ganesh_chaturthi",
        "Ganesh Chaturthi",
        "2027-09-04",
        "2027-09-14",
        10,
        3,
        1,
        NOTE_APPROX,
        checked=False,
    ),
    _festival(
        "diwali", "Diwali", "2027-10-29", "2027-11-02", 14, 4, 2, NOTE_APPROX, checked=False
    ),
)


def upsert_tax_rates(session: Session) -> int:
    rows = [
        {
            "code": code,
            "rate_pct": Decimal(rate),
            "label": label,
            "effective_from": GST_EFFECTIVE_FROM,
            "notes": GST_NOTE,
        }
        for code, rate, label in TAX_RATES
    ]
    stmt = insert(TaxRate).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TaxRate.code],
        set_={
            "rate_pct": stmt.excluded.rate_pct,
            "label": stmt.excluded.label,
            "effective_from": stmt.excluded.effective_from,
            "notes": stmt.excluded.notes,
        },
    )
    session.execute(stmt)
    return len(rows)


def upsert_calendar_events(session: Session) -> int:
    rows = [
        {
            "slug": event.slug,
            "event_key": event.event_key,
            "name": event.name,
            "kind": event.kind,
            "start_date": event.start,
            "end_date": event.end,
            "pre_window_days": event.pre,
            "post_window_days": event.post,
            "delivery_delay_days": event.delay,
            "affects_hours": event.affects_hours,
            "is_verified": event.verified,
            "source_note": event.note,
        }
        for event in CALENDAR_EVENTS
    ]
    stmt = insert(CalendarEvent).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[CalendarEvent.slug],
        set_={
            "event_key": stmt.excluded.event_key,
            "name": stmt.excluded.name,
            "kind": stmt.excluded.kind,
            "start_date": stmt.excluded.start_date,
            "end_date": stmt.excluded.end_date,
            "pre_window_days": stmt.excluded.pre_window_days,
            "post_window_days": stmt.excluded.post_window_days,
            "delivery_delay_days": stmt.excluded.delivery_delay_days,
            "affects_hours": stmt.excluded.affects_hours,
            "is_verified": or_(CalendarEvent.is_verified, stmt.excluded.is_verified),
            "source_note": stmt.excluded.source_note,
        },
        where=func.coalesce(CalendarEvent.source_note, "") != OWNER_NOTE,
    )
    session.execute(stmt)
    return len(rows)


def upsert_reference_data(session: Session) -> dict[str, int]:
    """Insert or refresh all reference rows. Safe to run on every deploy."""
    counts = {
        "tax_rates": upsert_tax_rates(session),
        "calendar_events": upsert_calendar_events(session),
    }
    log.info("reference_data.upserted", **counts)
    return counts
