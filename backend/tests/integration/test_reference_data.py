from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.jobs.reference_data import CALENDAR_EVENTS, upsert_reference_data
from app.models.reference import CalendarEvent, TaxRate


def event(db: Session, slug: str) -> CalendarEvent:
    return db.execute(select(CalendarEvent).where(CalendarEvent.slug == slug)).scalar_one()


def test_tax_rates_follow_the_post_september_2025_structure(db: Session) -> None:
    rates = {r.code: r for r in db.execute(select(TaxRate)).scalars()}
    assert {code: r.rate_pct for code, r in rates.items()} == {
        "GST0": Decimal("0.00"),
        "GST5": Decimal("5.00"),
        "GST18": Decimal("18.00"),
        "GST40": Decimal("40.00"),
    }
    assert all(r.effective_from == date(2025, 9, 22) for r in rates.values())
    assert all("not tax advice" in (r.notes or "") for r in rates.values())


def test_every_calendar_row_from_the_spec_is_present(db: Session) -> None:
    count = db.execute(select(func.count()).select_from(CalendarEvent)).scalar_one()
    assert count == len(CALENDAR_EVENTS) == 28
    diwali = event(db, "diwali-2026")
    assert (diwali.start_date, diwali.end_date) == (date(2026, 11, 6), date(2026, 11, 10))
    assert (diwali.pre_window_days, diwali.post_window_days, diwali.delivery_delay_days) == (
        14,
        4,
        2,
    )
    assert diwali.affects_hours is True
    assert event(db, "ganesh_chaturthi-2026").delivery_delay_days == 1
    assert event(db, "navratri_dussehra-2026").start_date == date(2026, 10, 11)


def test_festival_dates_are_unverified_and_seasons_are_not(db: Session) -> None:
    events = db.execute(select(CalendarEvent)).scalars().all()
    festivals = [e for e in events if e.kind == "festival"]
    seasons = [e for e in events if e.kind == "season"]
    assert festivals
    assert all(e.is_verified is False for e in festivals)
    assert seasons
    assert all(e.is_verified is True for e in seasons)


def test_2027_rows_are_marked_approximate(db: Session) -> None:
    rows = db.execute(
        select(CalendarEvent).where(CalendarEvent.start_date >= date(2027, 1, 1))
    ).scalars()
    approximate = [e for e in rows if e.slug.endswith("-2027")]
    assert len(approximate) == 6
    assert all("Approximate" in (e.source_note or "") for e in approximate)


def test_no_dashes_in_stored_text(db: Session) -> None:
    for row in db.execute(select(CalendarEvent)).scalars():
        for text in (row.name, row.source_note or ""):
            assert "\u2014" not in text
            assert "\u2013" not in text


def test_upsert_is_idempotent(db: Session) -> None:
    before = db.execute(select(func.count()).select_from(CalendarEvent)).scalar_one()
    for _ in range(2):
        counts = upsert_reference_data(db)
    after = db.execute(select(func.count()).select_from(CalendarEvent)).scalar_one()
    assert counts == {"tax_rates": 4, "calendar_events": 28}
    assert before == after


def test_upsert_never_unverifies_a_checked_date(db: Session) -> None:
    diwali = event(db, "diwali-2026")
    diwali.is_verified = True
    db.flush()
    upsert_reference_data(db)
    db.refresh(diwali)
    assert diwali.is_verified is True


def test_upsert_leaves_owner_edits_and_visibility_alone(db: Session) -> None:
    holi = event(db, "holi-2026")
    holi.name = "Holi (our shop closes early)"
    holi.source_note = "owner"
    db.flush()
    upsert_reference_data(db)
    db.refresh(holi)
    assert holi.name == "Holi (our shop closes early)"

    gudi = event(db, "gudi_padwa-2026")
    gudi.is_active = False
    db.flush()
    upsert_reference_data(db)
    db.refresh(gudi)
    assert gudi.is_active is False


def test_upsert_restores_a_changed_seed_row(db: Session) -> None:
    eid = event(db, "eid_fitr-2026")
    eid.pre_window_days = 1
    db.flush()
    upsert_reference_data(db)
    db.refresh(eid)
    assert eid.pre_window_days == 7
