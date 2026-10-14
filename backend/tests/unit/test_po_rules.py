"""Purchase order state machine and receipt rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.po_rules import (
    OPEN_STATUSES,
    TRANSITIONS,
    can_edit,
    days_late,
    invoice_differs,
    is_overdue,
    next_status,
    open_quantity,
    price_variance,
    status_after_receipt,
)
from app.models.purchasing import PO_STATUSES

D = Decimal
TODAY = date(2026, 10, 13)


def test_every_status_has_a_transition_entry() -> None:
    assert set(TRANSITIONS) == set(PO_STATUSES)


@pytest.mark.parametrize(
    ("status", "action", "expected"),
    [
        ("draft", "send", "sent"),
        ("draft", "cancel", "cancelled"),
        ("draft", "close", None),
        ("draft", "receive", None),
        ("sent", "cancel", "cancelled"),
        ("sent", "close", "closed"),
        ("sent", "receive", "partially_received"),
        ("sent", "send", None),
        ("partially_received", "receive", "partially_received"),
        ("partially_received", "close", "closed"),
        ("partially_received", "cancel", None),
        ("received", "close", "closed"),
        ("received", "receive", None),
        ("received", "cancel", None),
        ("cancelled", "send", None),
        ("cancelled", "close", None),
        ("closed", "receive", None),
        ("closed", "cancel", None),
    ],
)
def test_transitions(status: str, action: str, expected: str | None) -> None:
    assert next_status(status, action) == expected  # type: ignore[arg-type]


def test_only_a_draft_can_be_edited() -> None:
    assert [s for s in PO_STATUSES if can_edit(s)] == ["draft"]


def test_terminal_statuses_allow_nothing() -> None:
    assert TRANSITIONS["cancelled"] == {}
    assert TRANSITIONS["closed"] == {}


def test_open_quantity_never_goes_negative() -> None:
    assert open_quantity(D(10), D(4)) == D(6)
    assert open_quantity(D(10), D(10)) == D(0)
    assert open_quantity(D(10), D(12)) == D(0)


def test_status_after_receipt() -> None:
    assert status_after_receipt([(D(10), D(10)), (D(5), D(5))]) == "received"
    assert status_after_receipt([(D(10), D(12)), (D(5), D(5))]) == "received"
    assert status_after_receipt([(D(10), D(10)), (D(5), D(4))]) == "partially_received"
    assert status_after_receipt([(D(10), D(0))]) == "partially_received"
    assert status_after_receipt([]) == "partially_received"


@pytest.mark.parametrize(
    ("status", "expected", "late"),
    [
        ("sent", TODAY - timedelta(days=6), 6),
        ("partially_received", TODAY - timedelta(days=1), 1),
        ("sent", TODAY, 0),
        ("sent", TODAY + timedelta(days=2), 0),
        ("sent", None, 0),
        ("draft", TODAY - timedelta(days=6), 0),
        ("received", TODAY - timedelta(days=6), 0),
        ("cancelled", TODAY - timedelta(days=6), 0),
        ("closed", TODAY - timedelta(days=6), 0),
    ],
)
def test_overdue_detection(status: str, expected: date | None, late: int) -> None:
    assert days_late(status, expected, TODAY) == late
    assert is_overdue(status, expected, TODAY) == (late > 0)


@pytest.mark.parametrize(
    ("order", "paid", "variance"),
    [
        ("100", "100", None),
        ("100", "110", None),  # exactly 10 percent is not flagged
        ("100", "110.01", "0.1001"),
        ("100", "89", "-0.11"),
        ("100", "90", None),
        ("0", "5", None),
    ],
)
def test_price_variance_flags_more_than_ten_percent(
    order: str, paid: str, variance: str | None
) -> None:
    result = price_variance(D(order), D(paid))
    if variance is None:
        assert result is None
    else:
        assert result is not None
        assert round(result, 4) == D(variance)


@given(
    order=st.decimals(min_value=D("0.01"), max_value=D(10000), places=2),
    factor=st.decimals(min_value=D("0.5"), max_value=D(2), places=3),
)
def test_price_variance_is_none_exactly_within_ten_percent(order: Decimal, factor: Decimal) -> None:
    paid = order * factor
    change = (paid - order) / order
    assert (price_variance(order, paid) is None) == (abs(change) <= D("0.10"))


def test_invoice_total_check_allows_a_rupee_of_rounding() -> None:
    assert not invoice_differs(None, D("500.00"))
    assert not invoice_differs(D("500.00"), D("500.00"))
    assert not invoice_differs(D("501.00"), D("500.00"))
    assert invoice_differs(D("501.01"), D("500.00"))
    assert invoice_differs(D("498.99"), D("500.00"))


def test_only_sent_and_partly_received_orders_are_open() -> None:
    assert {"sent", "partially_received"} == OPEN_STATUSES
