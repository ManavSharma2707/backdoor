"""Lead time resolution, delivery dates and the term overlap rules."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.lead_time import (
    DEFAULT_LEAD_TIME_DAYS,
    LeadTime,
    expected_delivery_date,
    next_delivery_date,
    resolve_lead_time,
)
from app.engine.term_rules import Span, overlaps, plan_new_span

# --------------------------------------------------------------------------- lead time


def test_product_term_wins_over_supplier_and_business() -> None:
    assert resolve_lead_time(5, 2, 4) == LeadTime(5, "product_term")


def test_supplier_default_is_used_when_the_term_has_none() -> None:
    assert resolve_lead_time(None, 2, 4) == LeadTime(2, "supplier_default")


def test_business_default_is_the_last_resort_and_is_assumed() -> None:
    lead = resolve_lead_time(None, None, 4)
    assert lead == LeadTime(4, "business_default")
    assert lead.is_assumed
    assert not resolve_lead_time(1, None, 4).is_assumed


def test_falls_back_to_three_days_when_even_the_business_value_is_missing() -> None:
    assert resolve_lead_time(None, None, None) == LeadTime(
        DEFAULT_LEAD_TIME_DAYS, "business_default"
    )
    assert resolve_lead_time(None, None) == LeadTime(3, "business_default")


def test_zero_days_is_a_real_lead_time_not_a_missing_one() -> None:
    assert resolve_lead_time(0, 5, 7) == LeadTime(0, "product_term")
    assert resolve_lead_time(None, 0, 7) == LeadTime(0, "supplier_default")
    assert resolve_lead_time(None, None, 0) == LeadTime(0, "business_default")


@given(
    term=st.none() | st.integers(0, 60),
    supplier=st.none() | st.integers(0, 60),
    business=st.none() | st.integers(0, 60),
)
def test_resolution_order_property(
    term: int | None, supplier: int | None, business: int | None
) -> None:
    lead = resolve_lead_time(term, supplier, business)
    if term is not None:
        assert (lead.days, lead.source) == (term, "product_term")
    elif supplier is not None:
        assert (lead.days, lead.source) == (supplier, "supplier_default")
    else:
        assert lead.source == "business_default"
        assert lead.days == (DEFAULT_LEAD_TIME_DAYS if business is None else business)


# --------------------------------------------------------------------------- delivery dates


MONDAY = date(2026, 10, 12)


def test_every_day_is_a_delivery_day_without_a_weekday_list() -> None:
    assert next_delivery_date(MONDAY, None) == MONDAY
    assert next_delivery_date(MONDAY, []) == MONDAY


def test_moves_forward_to_the_next_delivery_weekday() -> None:
    tuesday_friday = [2, 5]
    assert next_delivery_date(MONDAY, tuesday_friday) == date(2026, 10, 13)
    assert next_delivery_date(date(2026, 10, 13), tuesday_friday) == date(2026, 10, 13)
    assert next_delivery_date(date(2026, 10, 14), tuesday_friday) == date(2026, 10, 16)
    assert next_delivery_date(date(2026, 10, 17), tuesday_friday) == date(2026, 10, 20)


def test_expected_date_adds_lead_time_first() -> None:
    lead = LeadTime(3, "product_term")
    # Monday + 3 days is Thursday, the next Tuesday or Friday delivery is Friday.
    assert expected_delivery_date(MONDAY, lead, [2, 5]) == date(2026, 10, 16)
    assert expected_delivery_date(MONDAY, lead, None) == date(2026, 10, 15)


@given(
    earliest=st.dates(min_value=date(2025, 1, 1), max_value=date(2030, 1, 1)),
    weekdays=st.lists(st.integers(1, 7), min_size=1, max_size=7),
)
def test_next_delivery_is_never_early_and_lands_on_a_delivery_day(
    earliest: date, weekdays: list[int]
) -> None:
    found = next_delivery_date(earliest, weekdays)
    assert found >= earliest
    assert found - earliest <= timedelta(days=6)
    assert found.isoweekday() in weekdays


def test_out_of_range_weekdays_are_ignored() -> None:
    assert next_delivery_date(MONDAY, [0, 8, 99]) == MONDAY


# --------------------------------------------------------------------------- term spans


D = date


def test_overlap_is_inclusive_and_open_ended_aware() -> None:
    assert overlaps(D(2026, 1, 1), D(2026, 1, 31), D(2026, 1, 31), D(2026, 2, 28))
    assert not overlaps(D(2026, 1, 1), D(2026, 1, 30), D(2026, 1, 31), None)
    assert overlaps(D(2026, 1, 1), None, D(2030, 1, 1), None)
    assert overlaps(D(2026, 1, 1), None, D(2020, 1, 1), D(2026, 1, 1))
    assert not overlaps(D(2026, 1, 2), None, D(2020, 1, 1), D(2026, 1, 1))


def test_new_open_ended_term_closes_the_earlier_open_ended_one() -> None:
    existing = [Span("old", D(2026, 1, 1), None)]
    plan = plan_new_span(existing, D(2026, 10, 1), None)
    assert plan.allowed
    assert plan.close == (("old", D(2026, 9, 30)),)


def test_a_term_inside_an_open_ended_one_is_a_conflict() -> None:
    existing = [Span("old", D(2026, 1, 1), None)]
    plan = plan_new_span(existing, D(2026, 10, 1), D(2026, 10, 31))
    assert not plan.allowed
    assert plan.conflicts == ("old",)


def test_same_start_or_earlier_start_conflicts() -> None:
    existing = [Span("a", D(2026, 10, 1), None)]
    assert not plan_new_span(existing, D(2026, 10, 1), None).allowed
    assert not plan_new_span(existing, D(2026, 9, 1), None).allowed


def test_non_overlapping_terms_are_left_alone() -> None:
    existing = [Span("past", D(2025, 1, 1), D(2025, 12, 31)), Span("future", D(2027, 1, 1), None)]
    plan = plan_new_span(existing, D(2026, 1, 1), D(2026, 12, 31))
    assert plan.allowed
    assert plan.close == ()


def test_a_closed_term_that_overlaps_conflicts() -> None:
    existing = [Span("a", D(2026, 1, 1), D(2026, 6, 30))]
    assert not plan_new_span(existing, D(2026, 6, 30), None).allowed
    assert plan_new_span(existing, D(2026, 7, 1), None).allowed


def test_end_before_start_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="cannot end before"):
        plan_new_span([], D(2026, 2, 1), D(2026, 1, 1))


span_strategy = st.builds(
    lambda start, length: (start, None if length is None else start + timedelta(days=length)),
    st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 12, 31)),
    st.none() | st.integers(0, 400),
)


def add_span(
    spans: dict[int, tuple[date, date | None]], start: date, end: date | None
) -> dict[int, tuple[date, date | None]] | None:
    """Apply `plan_new_span` the way the service does. None when the plan refuses."""
    plan = plan_new_span([Span(i, s, e) for i, (s, e) in spans.items()], start, end)
    if not plan.allowed:
        return None
    result = dict(spans)
    for key, new_end in plan.close:
        assert isinstance(key, int)
        result[key] = (result[key][0], new_end)
    result[max(result, default=-1) + 1] = (start, end)
    return result


@given(existing=st.lists(span_strategy, max_size=6), new=span_strategy)
def test_applying_a_plan_never_leaves_two_terms_in_force_on_the_same_day(
    existing: list[tuple[date, date | None]], new: tuple[date, date | None]
) -> None:
    """Build a valid set by adding spans one at a time, add one more: still no overlaps."""
    spans: dict[int, tuple[date, date | None]] = {}
    for start, end in [*existing, new]:
        spans = add_span(spans, start, end) or spans
    items = list(spans.values())
    for i, (a_start, a_end) in enumerate(items):
        for b_start, b_end in items[i + 1 :]:
            assert not overlaps(a_start, a_end, b_start, b_end)
