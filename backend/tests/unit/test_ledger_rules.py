"""Pure ledger rules: movement signs, weighted average cost, FEFO allocation, bill arithmetic."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.ledger_rules import (
    SIGN_RULES,
    BatchStock,
    LedgerRuleError,
    allocate_fefo,
    batch_problem,
    check_movement,
    fefo_order,
    is_sellable,
    weighted_average_cost,
)
from app.engine.sales_math import gross_amount, refund_for, split_discount, tax_contained
from app.models.inventory import MOVEMENT_TYPES

D = Decimal
TODAY = date(2026, 10, 13)


# --------------------------------------------------------------------------- movement signs


def test_every_movement_type_has_a_sign_rule() -> None:
    assert set(SIGN_RULES) == set(MOVEMENT_TYPES)


@pytest.mark.parametrize(
    ("movement_type", "delta", "ok"),
    [
        ("opening", "5", True),
        ("opening", "-5", False),
        ("receipt", "5", True),
        ("receipt", "-1", False),
        ("sale", "-1", True),
        ("sale", "1", False),
        ("void_reversal", "2", True),
        ("void_reversal", "-2", False),
        ("return_in", "1", True),
        ("return_in", "-1", False),
        ("damage", "-1", True),
        ("damage", "1", False),
        ("expiry_writeoff", "-3", True),
        ("expiry_writeoff", "3", False),
        ("supplier_return", "-3", True),
        ("supplier_return", "3", False),
        ("adjustment", "4", True),
        ("adjustment", "-4", True),
        ("count_correction", "4", True),
        ("count_correction", "-4", True),
    ],
)
def test_sign_rules(movement_type: str, delta: str, ok: bool) -> None:
    if ok:
        check_movement(movement_type, D(delta))
    else:
        with pytest.raises(LedgerRuleError):
            check_movement(movement_type, D(delta))


@pytest.mark.parametrize("movement_type", sorted(SIGN_RULES))
def test_a_zero_movement_is_never_valid(movement_type: str) -> None:
    with pytest.raises(LedgerRuleError, match="cannot be zero"):
        check_movement(movement_type, D(0))


def test_unknown_movement_type_is_refused() -> None:
    with pytest.raises(LedgerRuleError, match="Unknown movement type"):
        check_movement("teleport", D(1))


# --------------------------------------------------------------------------- weighted average


def test_weighted_average_worked_example() -> None:
    # 10 units at 8.00 plus 30 units at 9.00 is 40 units at 8.75.
    assert weighted_average_cost(D(10), D("8.0000"), D(30), D("9.0000")) == D("8.7500")


def test_empty_stock_takes_the_new_cost_outright() -> None:
    assert weighted_average_cost(D(0), D("99.0000"), D(5), D("7.1234")) == D("7.1234")


def test_weighted_average_rounds_half_up_to_four_places() -> None:
    assert weighted_average_cost(D(1), D("1.0000"), D(2), D("1.0001")) == D("1.0001")
    assert weighted_average_cost(D(1), D("0.0000"), D(1), D("0.0001")) == D("0.0001")


def test_weighted_average_needs_a_positive_quantity() -> None:
    with pytest.raises(LedgerRuleError):
        weighted_average_cost(D(1), D(1), D(0), D(1))


cost = st.decimals(min_value=D("0.0001"), max_value=D("5000"), places=4)
qty = st.decimals(min_value=D("0.001"), max_value=D("5000"), places=3)
stock = st.decimals(min_value=D(0), max_value=D("5000"), places=3)


@given(on_hand=stock, average=cost, added=qty, added_cost=cost)
def test_weighted_average_lies_between_the_two_costs(
    on_hand: Decimal, average: Decimal, added: Decimal, added_cost: Decimal
) -> None:
    result = weighted_average_cost(on_hand, average, added, added_cost)
    low, high = sorted((average, added_cost)) if on_hand > 0 else (added_cost, added_cost)
    assert low - D("0.0001") <= result <= high + D("0.0001")


@given(on_hand=stock, average=cost, added=qty, added_cost=cost)
def test_weighted_average_keeps_the_total_value_within_rounding(
    on_hand: Decimal, average: Decimal, added: Decimal, added_cost: Decimal
) -> None:
    result = weighted_average_cost(on_hand, average, added, added_cost)
    expected_value = (on_hand * average if on_hand > 0 else D(0)) + added * added_cost
    assert abs(result * (on_hand + added) - expected_value) <= (on_hand + added) * D("0.00005") + D(
        "0.0001"
    )


# --------------------------------------------------------------------------- FEFO


def batch(number: str, days: int, on_hand: str, status: str = "active") -> BatchStock:
    return BatchStock(
        batch_id=uuid.uuid5(uuid.NAMESPACE_DNS, number),
        batch_no=number,
        expiry_date=TODAY + timedelta(days=days),
        on_hand=D(on_hand),
        status=status,
    )


def test_fefo_takes_the_earliest_expiry_first_and_splits() -> None:
    late, early, middle = batch("L", 300, "50"), batch("E", 30, "4"), batch("M", 90, "10")
    result = allocate_fefo([late, early, middle], D(12), TODAY)
    assert result.parts == ((early.batch_id, D(4)), (middle.batch_id, D(8)))
    assert result.complete


def test_fefo_skips_expired_quarantined_and_empty_batches() -> None:
    expired = batch("X", -1, "9")
    expires_today = batch("T", 0, "9")  # the expiry date is the first day it cannot be sold
    quarantined = batch("Q", 20, "9", "quarantined")
    empty = batch("Z", 25, "0")
    fine = batch("F", 40, "3")
    result = allocate_fefo([expired, expires_today, quarantined, empty, fine], D(2), TODAY)
    assert result.parts == ((fine.batch_id, D(2)),)


def test_fefo_reports_a_shortfall_when_stock_runs_out() -> None:
    result = allocate_fefo([batch("A", 10, "3"), batch("B", 20, "2")], D(7), TODAY)
    assert sum(q for _, q in result.parts) == D(5)
    assert result.shortfall == D(2)
    assert not result.complete


def test_fefo_ties_break_on_the_batch_number() -> None:
    a, b = batch("A1", 30, "5"), batch("B1", 30, "5")
    assert [x.batch_no for x in fefo_order([b, a])] == ["A1", "B1"]


def test_fefo_needs_a_positive_quantity() -> None:
    with pytest.raises(LedgerRuleError):
        allocate_fefo([batch("A", 10, "3")], D(0), TODAY)


@pytest.mark.parametrize(
    ("days", "on_hand", "status", "quantity", "problem"),
    [
        (10, "5", "active", "5", None),
        (10, "5", "active", "6", "short"),
        (0, "5", "active", "1", "expired"),
        (-5, "5", "active", "1", "expired"),
        (10, "5", "quarantined", "1", "unavailable"),
        (10, "5", "closed", "1", "unavailable"),
    ],
)
def test_batch_problem(
    days: int, on_hand: str, status: str, quantity: str, problem: str | None
) -> None:
    assert batch_problem(batch("A", days, on_hand, status), D(quantity), TODAY) == problem


batches = st.lists(
    st.builds(
        BatchStock,
        batch_id=st.builds(uuid.uuid4),
        batch_no=st.text(alphabet="ABCDEFGH0123", min_size=1, max_size=4),
        expiry_date=st.dates(
            min_value=TODAY - timedelta(days=60), max_value=TODAY + timedelta(days=400)
        ),
        on_hand=st.decimals(min_value=D(0), max_value=D(100), places=3),
        status=st.sampled_from(["active", "active", "active", "quarantined", "closed"]),
    ),
    max_size=8,
)


@given(batches=batches, quantity=st.decimals(min_value=D("0.001"), max_value=D(500), places=3))
def test_fefo_allocation_properties(batches: list[BatchStock], quantity: Decimal) -> None:
    result = allocate_fefo(batches, quantity, TODAY)
    by_id = {b.batch_id: b for b in batches}
    sellable_total = sum((b.on_hand for b in batches if is_sellable(b, TODAY)), D(0))

    taken = sum((q for _, q in result.parts), D(0))
    assert taken + result.shortfall == quantity
    assert taken == min(quantity, sellable_total)
    assert result.complete == (sellable_total >= quantity)
    for batch_id, part in result.parts:
        source = by_id[batch_id]
        assert is_sellable(source, TODAY)  # never expired, inactive or empty
        assert 0 < part <= source.on_hand  # never more than the batch holds
    # Invariant 5: nothing is drawn from a later batch while an earlier sellable one has stock.
    drawn = dict(result.parts)
    ordered = fefo_order([b for b in batches if is_sellable(b, TODAY)])
    seen_untouched_or_partial = False
    for candidate in ordered:
        part = drawn.get(candidate.batch_id, D(0))
        if seen_untouched_or_partial:
            assert part == 0
        if part < candidate.on_hand:
            seen_untouched_or_partial = True


# --------------------------------------------------------------------------- bill arithmetic


def test_gross_amount_rounds_to_paise_half_up() -> None:
    assert gross_amount(D("2"), D("9.5000")) == D("19.00")
    assert gross_amount(D("0.333"), D("10.0000")) == D("3.33")
    assert gross_amount(D("1.5"), D("0.3300")) == D("0.50")  # 0.495 rounds up


@pytest.mark.parametrize(
    ("total", "rate", "expected"),
    [
        ("105.00", "5", "5.00"),
        ("118.00", "18", "18.00"),
        ("140.00", "40", "40.00"),
        ("100.00", "0", "0.00"),
        ("19.00", "5", "0.90"),
    ],
)
def test_tax_contained_in_an_inclusive_price(total: str, rate: str, expected: str) -> None:
    assert tax_contained(D(total), D(rate)) == D(expected)


def test_split_discount_follows_gross_and_adds_up() -> None:
    assert split_discount(D("10.00"), [D("30.00"), D("70.00")]) == [D("3.00"), D("7.00")]
    shares = split_discount(D("1.00"), [D("1.00"), D("1.00"), D("1.00")])
    assert sum(shares) == D("1.00")
    assert sorted(shares) == [D("0.33"), D("0.33"), D("0.34")]
    assert split_discount(D("0"), [D("5.00"), D("5.00")]) == [D("0.00"), D("0.00")]


def test_split_discount_refuses_more_than_the_gross() -> None:
    with pytest.raises(ValueError, match="between zero and the gross"):
        split_discount(D("10.01"), [D("5.00"), D("5.00")])


@given(
    grosses=st.lists(
        st.decimals(min_value=D("0.01"), max_value=D(5000), places=2), min_size=1, max_size=6
    ),
    share=st.decimals(min_value=D(0), max_value=D(1), places=4),
)
def test_split_discount_properties(grosses: list[Decimal], share: Decimal) -> None:
    discount = (sum(grosses, D(0)) * share).quantize(D("0.01"))
    shares = split_discount(discount, grosses)
    assert sum(shares, D(0)) == discount
    for part, gross in zip(shares, grosses, strict=True):
        assert 0 <= part <= gross


def test_refund_for_whole_line_and_parts_add_up_exactly() -> None:
    # A line of 3 units at 33.33 total: three single unit returns refund exactly 33.33.
    parts = [refund_for(D("33.33"), D(3), D(i), D(1)) for i in range(3)]
    assert sum(parts) == D("33.33")
    assert refund_for(D("19.00"), D(2), D(0), D(2)) == D("19.00")
    assert refund_for(D("19.00"), D(2), D(1), D(1)) == D("9.50")


@pytest.mark.parametrize(
    ("quantity", "before", "returning"),
    [("0", "0", "1"), ("2", "0", "0"), ("2", "1.5", "1"), ("2", "-1", "1")],
)
def test_refund_for_rejects_impossible_quantities(
    quantity: str, before: str, returning: str
) -> None:
    with pytest.raises(ValueError, match=r"positive|more than was sold"):
        refund_for(D("10.00"), D(quantity), D(before), D(returning))


@given(
    line_total=st.decimals(min_value=D("0.01"), max_value=D(9999), places=2),
    quantity=st.integers(1, 40),
    cuts=st.lists(st.integers(1, 40), min_size=1, max_size=6),
)
def test_part_returns_never_refund_more_than_the_line_and_sum_to_it(
    line_total: Decimal, quantity: int, cuts: list[int]
) -> None:
    returned = 0
    refunded = D(0)
    for cut in cuts:
        step = min(cut, quantity - returned)
        if step == 0:
            break
        refunded += refund_for(line_total, D(quantity), D(returned), D(step))
        returned += step
    assert refunded <= line_total
    if returned == quantity:
        assert refunded == line_total
