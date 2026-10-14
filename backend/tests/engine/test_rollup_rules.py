"""Hand computed cases for the daily rollup rules (`engine-spec.md` section 3)."""

from datetime import date, timedelta

import numpy as np

from app.engine import rollup as r

START = date(2026, 1, 5)  # a Monday


def arr(*rows: list[int]) -> np.ndarray:
    return np.array(rows, dtype=np.int64)


def states(codes: np.ndarray) -> list[str]:
    return r.state_names(codes)[0]


def run_case(
    *,
    pre: int,
    net: list[int],
    receipts: list[int],
    sold: list[int],
    launched: date | None = None,
    first: date | None = date(2026, 1, 1),
    intervals: list[r.Interval] | None = None,
) -> list[str]:
    opening, closing = r.running_balances(np.array([pre]), arr(net))
    forced = r.forced_by_intervals(len(net), START, [intervals or []])
    codes = r.classify_availability(
        start=START,
        opening=opening,
        closing=closing,
        receipts=arr(receipts),
        units_sold=arr(sold),
        launched_on=[launched],
        first_ledger_day=[first],
        forced=forced,
    )
    return states(codes)


def test_running_balances_chain_opening_to_closing() -> None:
    opening, closing = r.running_balances(np.array([10, 0]), arr([-4, -6, 0, 20], [0, 5, -2, 0]))
    assert opening.tolist() == [[10, 6, 0, 0], [0, 0, 5, 3]]
    assert closing.tolist() == [[6, 0, 0, 20], [0, 5, 3, 3]]


def test_every_state_of_a_week_by_hand() -> None:
    # 10 on the shelf. Day 1 sells 4, day 2 sells the last 6, day 3 nothing is there, day 4
    # a delivery of 20 arrives, days 5 and 6 sell 5 and 3.
    got = run_case(
        pre=10, net=[-4, -6, 0, 20, -5, -3], receipts=[0, 0, 0, 20, 0, 0], sold=[4, 6, 0, 0, 5, 3]
    )
    assert got == [r.AVAILABLE, r.SOLD_OUT, r.STOCKED_OUT, r.AVAILABLE, r.AVAILABLE, r.AVAILABLE]


def test_receipt_on_an_empty_shelf_is_not_a_stockout() -> None:
    got = run_case(pre=0, net=[12, -3], receipts=[12, 0], sold=[0, 3])
    assert got == [r.AVAILABLE, r.AVAILABLE]


def test_closing_at_zero_without_a_sale_is_available() -> None:
    # A write off took the stock to zero at the end of the day. Nothing was turned away.
    got = run_case(pre=5, net=[-5, 0], receipts=[0, 0], sold=[0, 0])
    assert got == [r.AVAILABLE, r.STOCKED_OUT]


def test_recorded_interval_forces_stockout_or_sold_out() -> None:
    got = run_case(
        pre=50,
        net=[-1, -1, -1],
        receipts=[0, 0, 0],
        sold=[1, 0, 1],
        intervals=[r.Interval(START + timedelta(days=1), START + timedelta(days=2))],
    )
    assert got == [r.AVAILABLE, r.STOCKED_OUT, r.SOLD_OUT]


def test_open_recorded_interval_runs_to_the_end() -> None:
    got = run_case(
        pre=50,
        net=[0, 0, 0],
        receipts=[0, 0, 0],
        sold=[0, 0, 0],
        intervals=[r.Interval(START + timedelta(days=1), None)],
    )
    assert got == [r.AVAILABLE, r.STOCKED_OUT, r.STOCKED_OUT]


def test_not_launched_and_unknown_win_over_stock_rules() -> None:
    got = run_case(
        pre=0,
        net=[0, 0, 7, -1],
        receipts=[0, 0, 7, 0],
        sold=[0, 0, 0, 1],
        launched=START + timedelta(days=1),
        first=START + timedelta(days=2),
    )
    # Day 0 is before launch, day 1 and 2 have no ledger history before them, day 3 is normal.
    assert got == [r.NOT_LAUNCHED, r.UNKNOWN, r.UNKNOWN, r.AVAILABLE]


def test_product_without_any_ledger_entry_is_unknown() -> None:
    got = run_case(pre=0, net=[0, 0], receipts=[0, 0], sold=[0, 0], first=None)
    assert got == [r.UNKNOWN, r.UNKNOWN]


def test_censored_flag_follows_the_two_stock_states() -> None:
    opening, closing = r.running_balances(np.array([3]), arr([-3, 0, 5]))
    codes = r.classify_availability(
        start=START,
        opening=opening,
        closing=closing,
        receipts=arr([0, 0, 5]),
        units_sold=arr([3, 0, 0]),
        launched_on=[None],
        first_ledger_day=[date(2026, 1, 1)],
        forced=np.zeros((1, 3), dtype=np.bool_),
    )
    assert states(codes) == [r.SOLD_OUT, r.STOCKED_OUT, r.AVAILABLE]
    assert r.is_censored(codes).tolist() == [[True, True, False]]


def test_stockout_runs_need_the_minimum_length() -> None:
    codes = np.array([0, 1, 1, 0, 1, 0, 1, 1, 1], dtype=np.int64)  # 0 available, 1 stocked out
    runs = r.stockout_runs(codes, START, 2)
    assert [(x.first, x.last, x.days) for x in runs] == [
        (START + timedelta(days=1), START + timedelta(days=2), 2),
        (START + timedelta(days=6), START + timedelta(days=8), 3),
    ]
