"""FEFO simulation, inventory state, risk bands and budget allocation, with the properties of
`testing-strategy.md` section 3 (items 7, 9 and 10)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engine.budget import BudgetLine, allocate, percentile_ranks, priority_scores
from app.engine.deadstock import excess_quantity, stock_status
from app.engine.expiry import SimBatch, demand_between, extend_forecast, simulate_fefo
from app.engine.inputs import BatchInfo, IncomingLine, ProductInfo
from app.engine.inventory_state import Arrival, stock_state
from app.engine.risk import (
    RiskInput,
    classify_risk,
    days_of_cover,
    expected_units_short,
    projected_stockout_date,
    stockout_probability,
)

AS_OF = date(2026, 10, 12)


def day(n: int) -> date:
    return AS_OF + timedelta(days=n)


# ------------------------------------------------------------------------------ FEFO


def test_fefo_consumes_the_earliest_expiry_first() -> None:
    batches = [SimBatch("late", 10, day(60)), SimBatch("early", 10, day(20))]
    res = simulate_fefo(batches, np.full(28, 1.0), AS_OF, 28)
    by = {b.key: b for b in res.batches}
    assert by["early"].expected_sold == pytest.approx(10.0)
    assert by["early"].expected_loss == 0.0
    assert by["late"].expected_sold == pytest.approx(10.0)  # 18 more days to sell it


def test_slow_demand_makes_the_early_batch_a_loss() -> None:
    batches = [SimBatch("early", 40, day(10), Decimal("5")), SimBatch("late", 10, day(100))]
    res = simulate_fefo(batches, np.full(28, 1.0), AS_OF, 28)
    early = next(b for b in res.batches if b.key == "early")
    assert early.expected_sold == pytest.approx(10.0)  # one a day for the 10 days it lives
    assert early.expected_loss == pytest.approx(30.0)
    assert early.loss_value == Decimal("150.00")
    assert res.lost == pytest.approx(30.0)


def test_batches_beyond_the_horizon_are_followed_to_their_expiry() -> None:
    # 100 units expiring on day 60, demand 1 a day at the end of the horizon.
    batches = [SimBatch("b", 100, day(60))]
    res = simulate_fefo(batches, np.full(28, 1.0), AS_OF, 28)
    assert res.batches[0].expected_sold == pytest.approx(60.0)
    assert res.batches[0].expected_loss == pytest.approx(40.0)
    assert len(res.daily_stock) == 61


def test_extrapolation_stops_after_a_year() -> None:
    res = simulate_fefo([SimBatch("b", 10_000, day(900))], np.full(28, 1.0), AS_OF, 28)
    assert len(res.daily_stock) == 365
    assert res.batches[0].expected_loss == 0.0  # not simulated that far


def test_stock_that_never_expires_is_never_lost() -> None:
    res = simulate_fefo([SimBatch("plain", 50, None)], np.full(28, 0.0), AS_OF, 28)
    assert res.lost == 0.0
    assert res.remaining == 50.0


def test_an_already_expired_batch_is_lost_on_the_first_day() -> None:
    res = simulate_fefo([SimBatch("old", 8, AS_OF)], np.full(28, 5.0), AS_OF, 28)
    assert res.batches[0].expected_loss == 8.0
    assert res.consumed == 0.0


def test_arrivals_join_on_their_day_and_sell_after_older_stock() -> None:
    batches = [SimBatch("old", 5, day(30)), SimBatch("new", 20, day(90), arrives_on=day(3))]
    res = simulate_fefo(batches, np.full(28, 2.0), AS_OF, 28)
    old = res.batches[0]
    assert old.expected_sold == pytest.approx(5.0)
    assert res.arrivals == 20
    assert res.start_stock == 5
    assert res.daily_stock[2] == 0.0  # the old stock is gone before the delivery lands
    assert res.daily_stock[3] == pytest.approx(20 - 2)


def test_extension_and_demand_between() -> None:
    forecast = np.concatenate([np.full(14, 1.0), np.full(14, 3.0)])
    assert extend_forecast(forecast, 30).tolist() == [*forecast.tolist(), 3.0, 3.0]
    assert extend_forecast(forecast, 5).tolist() == [1.0] * 5
    assert demand_between(forecast, 0, 14) == 14.0
    assert demand_between(forecast, 26, 4) == 3 * 4
    assert demand_between(forecast, 0, 0) == 0.0
    assert extend_forecast(np.zeros(0), 3).tolist() == [0.0, 0.0, 0.0]


@settings(max_examples=150, deadline=None)
@given(
    lots=st.lists(
        st.tuples(
            st.floats(0, 100),
            st.one_of(st.none(), st.integers(1, 200)),
            st.one_of(st.none(), st.integers(0, 40)),
        ),
        min_size=1,
        max_size=6,
    ),
    rate=st.floats(0, 12),
)
def test_fefo_conserves_stock(
    lots: list[tuple[float, int | None, int | None]], rate: float
) -> None:
    """Consumed plus lost plus remaining equals the starting stock plus the arrivals."""
    batches = [
        SimBatch(
            f"b{i}",
            qty,
            day(exp) if exp else None,
            arrives_on=day(arr) if arr is not None and i % 2 else None,
        )
        for i, (qty, exp, arr) in enumerate(lots)
    ]
    res = simulate_fefo(batches, np.full(28, rate), AS_OF, 28)
    assert abs(res.balance_error) < 1e-6
    assert all(b.expected_loss >= -1e-9 and b.expected_sold >= -1e-9 for b in res.batches)
    for b in res.batches:
        assert b.expected_sold + b.expected_loss <= b.qty + 1e-6


# ------------------------------------------------------------------------------ inventory state


def product(**kw: object) -> ProductInfo:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "sku": "S",
        "name": "Biscuits",
        "category_id": uuid.uuid4(),
        "category_slug": "b",
        "category_name": "B",
        "is_active": True,
        "is_batch_tracked": True,
        "shelf_life_days": 180,
        "min_stock_qty": 0.0,
        "is_seasonal": False,
        "launched_on": date(2025, 1, 1),
        "first_seen": date(2025, 1, 1),
        "selling_price": Decimal("12"),
        "mrp": Decimal("12"),
        "base_unit": "pack",
        "pack_label": None,
        "avg_cost": Decimal("8"),
    }
    values.update(kw)
    return ProductInfo(**values)  # type: ignore[arg-type]


def test_state_splits_sellable_expired_and_quarantined() -> None:
    p = product(
        batches=(
            BatchInfo(uuid.uuid4(), "B1", 10.0, day(40), Decimal("7")),
            BatchInfo(uuid.uuid4(), "B0", 4.0, day(10), Decimal("7")),
            BatchInfo(uuid.uuid4(), "BX", 6.0, AS_OF, Decimal("7")),  # expires today: not sellable
            BatchInfo(uuid.uuid4(), "BQ", 3.0, day(90), Decimal("7"), status="quarantined"),
            BatchInfo(uuid.uuid4(), "BF", 2.0, day(90), Decimal("7"), status="expired"),
            BatchInfo(None, None, 5.0, None, Decimal(0)),
            BatchInfo(uuid.uuid4(), "BZ", 0.0, day(90), Decimal("7")),
        )
    )
    s = stock_state(p, AS_OF, day(3))
    assert s.on_hand_total == 30.0
    assert s.on_hand_sellable == 19.0  # 10 + 4 + 5
    assert s.expired_qty == 8.0
    assert s.expired_value == Decimal("56.000000")
    assert s.quarantined_qty == 3.0
    assert [b.batch_no for b in s.sellable] == [
        "B0",
        "B1",
        None,
    ]  # earliest expiry first, loose last
    assert s.sellable[2].unit_cost == Decimal("8")  # the average cost stands in


def test_state_open_orders_confirmed_and_overdue() -> None:
    sup = uuid.uuid4()
    p = product(
        incoming=(
            IncomingLine(uuid.uuid4(), "PO1", sup, 20.0, day(2)),
            IncomingLine(uuid.uuid4(), "PO2", sup, 8.0, AS_OF),  # arrives today, still confirmed
            IncomingLine(uuid.uuid4(), "PO3", sup, 30.0, day(-6)),  # six days late
            IncomingLine(uuid.uuid4(), "PO4", sup, 5.0, None),  # no date: assumed
            IncomingLine(uuid.uuid4(), "PO5", sup, 0.0, day(1)),
        )
    )
    s = stock_state(p, AS_OF, day(4))
    assert s.incoming_confirmed == 33.0
    assert s.incoming_overdue == 30.0
    assert s.overdue[0].days_late == 6
    assert [a.po_number for a in s.confirmed] == ["PO2", "PO1", "PO4"]
    assert s.incoming_by(day(2)) == 28.0
    assert Arrival(day(4), 5.0, "PO4") in s.confirmed


# ------------------------------------------------------------------------------ risk


def test_probability_follows_the_normal_curve() -> None:
    assert stockout_probability(10, 10, 5) == pytest.approx(0.5)
    assert stockout_probability(20, 10, 5) == pytest.approx(0.0228, abs=1e-4)
    assert stockout_probability(0, 10, 0) == 1.0
    assert stockout_probability(10, 10, 0) == 0.0
    assert stockout_probability(10.0001, 10, 0) == 0.0


@settings(max_examples=200, deadline=None)
@given(
    demand=st.floats(0, 200),
    sigma=st.floats(0.01, 50),
    s1=st.floats(0, 300),
    extra=st.floats(0, 200),
)
def test_probability_is_a_probability_and_falls_as_stock_rises(
    demand: float, sigma: float, s1: float, extra: float
) -> None:
    low = stockout_probability(s1, demand, sigma)
    high = stockout_probability(s1 + extra, demand, sigma)
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high <= low + 1e-12


def test_expected_units_short() -> None:
    assert expected_units_short(10, 10, 4) == pytest.approx(4 * 0.3989, abs=1e-3)
    assert expected_units_short(100, 10, 4) == pytest.approx(0.0, abs=1e-9)
    assert expected_units_short(4, 10, 0) == 6.0
    assert expected_units_short(10, 4, 0) == 0.0
    assert expected_units_short(5, 20, 3) > expected_units_short(10, 20, 3)


def risk(**kw: object) -> str:
    base: dict[str, object] = {
        "usable": 50.0,
        "avg_forecast": 3.0,
        "probability": 0.0,
        "stockout_on": None,
        "arrival": day(3),
        "service_level": 0.95,
        "order_suggested": False,
    }
    base.update(kw)
    return classify_risk(RiskInput(**base))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "level"),
    [
        ({"usable": 0.0}, "critical"),
        ({"usable": 0.0, "avg_forecast": 0.0}, "none"),
        ({"probability": 0.60}, "critical"),
        ({"probability": 0.599}, "high"),
        ({"probability": 0.30}, "high"),
        ({"probability": 0.299}, "medium"),
        ({"probability": 0.10}, "medium"),
        ({"probability": 0.099}, "medium"),
        ({"probability": 0.051}, "medium"),
        ({"probability": 0.05}, "none"),
        ({"probability": 0.02, "order_suggested": True}, "low"),
        ({"probability": 0.02, "order_suggested": False}, "none"),
        ({"stockout_on": day(3)}, "critical"),
        ({"stockout_on": day(4)}, "none"),
    ],
)
def test_risk_boundaries(kwargs: dict[str, object], level: str) -> None:
    assert risk(**kwargs) == level


def test_projected_stockout_date_counts_arrivals() -> None:
    forecast = np.full(28, 5.0)
    assert projected_stockout_date(20.0, [], forecast, AS_OF, 28) == day(4)  # 25 > 20 on day 4
    arrivals = [Arrival(day(3), 30.0, "PO")]
    assert projected_stockout_date(20.0, arrivals, forecast, AS_OF, 28) == day(10)
    assert projected_stockout_date(500.0, [], forecast, AS_OF, 28) is None
    assert projected_stockout_date(0.0, [], np.zeros(28), AS_OF, 28) is None


def test_days_of_cover() -> None:
    assert days_of_cover(30.0, np.full(28, 3.0)) == pytest.approx(10.0)
    assert days_of_cover(30.0, np.zeros(28)) is None


# ------------------------------------------------------------------------------ budget


def line(
    key: str,
    packs: int,
    *,
    cost: str | None = "10",
    pack: int = 10,
    moq: int = 0,
    p: float = 0.2,
    margin: float = 100.0,
    conf: str = "high",
    excess: float = 0.0,
) -> BudgetLine:
    return BudgetLine(
        key,
        packs,
        Decimal(pack),
        Decimal(moq),
        Decimal(cost) if cost else None,
        p,
        margin,
        conf,
        excess,
    )


def test_unconstrained_funds_everything() -> None:
    lines = [line("a", 3), line("b", 2)]
    res = allocate(lines, None, {})
    assert res.allocations["a"].packs == 3
    assert res.shortfall == Decimal(0)
    assert not res.constrained
    res2 = allocate(lines, Decimal("1000"), {})
    assert res2.funded == res2.needed == Decimal("500.00")
    assert res2.unfunded_lines == 0


def test_the_higher_score_is_funded_first_and_the_rest_gets_partial_packs() -> None:
    risky = line("risky", 5, p=0.9, margin=10.0)
    safe = line("safe", 5, p=0.05, margin=10.0)
    res = allocate([safe, risky], Decimal("700"), {})  # needs 1000
    assert res.constrained
    assert res.allocations["risky"].packs == 5
    assert res.allocations["safe"].packs == 2  # 200 left buys two packs of 100
    assert res.allocations["safe"].budget_limited
    assert res.allocations["safe"].unfunded_packs == 3
    assert res.funded == Decimal("700.00")
    assert res.shortfall == Decimal("300.00")
    assert res.unfunded_value == Decimal("300.00")
    assert res.unfunded_lines == 1


def test_a_partial_allocation_must_still_meet_the_minimum_order() -> None:
    big = line("big", 6, p=0.9, margin=900.0)
    small = line("small", 5, p=0.1, margin=10.0, moq=30)  # at least 3 packs of 10
    res = allocate([big, small], Decimal("700"), {})
    assert res.allocations["big"].packs == 6
    assert res.allocations["small"].packs == 1 or res.allocations["small"].packs == 0
    assert res.allocations["small"].packs == 0  # 100 left buys one pack, under the minimum of three


def test_a_cheaper_line_can_still_fit_after_a_bigger_one_did_not() -> None:
    first = line("first", 10, p=0.9, margin=500.0)  # 1000
    cheap = line("cheap", 1, cost="1", p=0.1, margin=1.0)  # 10
    res = allocate([first, cheap], Decimal("50"), {})
    assert res.allocations["first"].packs == 0
    assert res.allocations["cheap"].packs == 1


def test_lines_without_a_cost_are_blocked_not_funded() -> None:
    res = allocate([line("ok", 2), line("nocost", 4, cost=None)], Decimal("1000"), {})
    assert res.allocations["nocost"].blocked
    assert res.allocations["nocost"].packs == 0
    assert res.blocked_lines == 1
    assert res.needed == Decimal("200.00")  # the unknown cost is not guessed
    assert not res.allocations["nocost"].budget_limited


def test_priority_components_use_the_weights() -> None:
    lines = [
        line("a", 1, p=0.5, margin=10.0, conf="medium", excess=0.5),
        line("b", 1, p=0.1, margin=20.0, conf="low", excess=0.0),
    ]
    scores = priority_scores(
        lines, {"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}
    )
    score_a, parts_a = scores["a"]
    assert parts_a == {"risk": 0.5, "value": 0.0, "confidence": 0.7, "excess": 0.5}
    assert score_a == pytest.approx(0.45 * 0.5 + 0.0 + 0.15 * 0.7 - 0.10 * 0.5)
    assert scores["b"][1]["value"] == 1.0


def test_percentile_ranks_handle_ties() -> None:
    assert percentile_ranks([5, 5, 5]).tolist() == [0.5, 0.5, 0.5]
    assert percentile_ranks([1, 2, 3]).tolist() == [0.0, 0.5, 1.0]
    assert percentile_ranks([7]).tolist() == [1.0]
    assert percentile_ranks([]).tolist() == []


budget_lines = st.lists(
    st.builds(
        lambda i, packs, pack, cost, moq, p, m, c, e: line(
            f"l{i}", packs, cost=str(cost), pack=pack, moq=moq, p=p, margin=m, conf=c, excess=e
        ),
        st.just(0),
        st.integers(1, 12),
        st.sampled_from([1, 6, 10, 12]),
        st.decimals(min_value="0.5", max_value="200", places=2),
        st.sampled_from([0, 0, 12, 30]),
        st.floats(0, 1),
        st.floats(-50, 500),
        st.sampled_from(["high", "medium", "low"]),
        st.floats(0, 1),
    ),
    min_size=1,
    max_size=15,
)


@settings(max_examples=200, deadline=None)
@given(lines=budget_lines, budget=st.decimals(min_value="0", max_value="20000", places=2))
def test_budget_properties(lines: list[BudgetLine], budget: Decimal) -> None:
    lines = [
        BudgetLine(
            f"l{i}",
            ln.packs,
            ln.pack_size,
            ln.moq_units,
            ln.unit_cost,
            ln.stockout_probability,
            ln.expected_margin,
            ln.confidence,
            ln.excess_ratio,
        )
        for i, ln in enumerate(lines)
    ]
    res = allocate(lines, budget, {})
    by_key = {ln.key: ln for ln in lines}
    # 7a. total spend never exceeds the budget
    assert res.funded <= budget
    # 7b. partial allocations are whole packs within the need and meet the minimum order
    for key, a in res.allocations.items():
        ln = by_key[key]
        assert 0 <= a.packs <= ln.packs
        assert a.qty == ln.pack_size * a.packs
        if 0 < a.packs < ln.packs:
            assert a.packs >= ln.min_packs
    # 7c. greedy order: a line is short only when the budget left at its turn could not afford more
    order = sorted(res.allocations.values(), key=lambda a: (-(a.score or 0), a.key))
    if res.constrained:
        by_score = sorted(
            lines,
            key=lambda ln: (
                -res.allocations[ln.key].score,
                -ln.stockout_probability,
                ln.full_spend,
                ln.key,
            ),
        )
        remaining = budget
        for ln in by_score:
            a = res.allocations[ln.key]
            cost = ln.pack_cost
            assert cost is not None
            if a.packs < ln.packs:
                assert remaining < ln.full_spend  # it did not fit in full
                one_more = a.packs + 1
                if one_more >= ln.min_packs:
                    assert cost * one_more > remaining  # and one more pack would not fit either
            remaining -= a.spend
        assert remaining >= 0
    assert len(order) == len(lines)


@settings(max_examples=100, deadline=None)
@given(lines=budget_lines)
def test_more_budget_never_funds_less_in_total(lines: list[BudgetLine]) -> None:
    lines = [
        BudgetLine(
            f"l{i}",
            ln.packs,
            ln.pack_size,
            ln.moq_units,
            ln.unit_cost,
            ln.stockout_probability,
            ln.expected_margin,
            ln.confidence,
            ln.excess_ratio,
        )
        for i, ln in enumerate(lines)
    ]
    needed = allocate(lines, None, {}).needed
    small = allocate(lines, needed / 3, {})
    large = allocate(lines, needed, {})
    assert large.funded == needed
    assert small.funded <= large.funded
    assert large.unfunded_lines == 0


# ------------------------------------------------------------------------------ stock status


def status(**kw: object) -> str:
    n = 120
    base: dict[str, object] = {
        "demand": np.full(n, 2.0),
        "available": np.ones(n, dtype=bool),
        "as_of": AS_OF,
        "start": AS_OF - timedelta(days=n),
        "age_days": 400,
        "demand_class": "smooth",
        "on_hand": 40.0,
        "days_of_cover": 20.0,
        "is_seasonal": False,
        "in_season": True,
        "nonmoving_days": 60,
        "slow_cover_days": 90,
    }
    base.update(kw)
    return stock_status(**base).status  # type: ignore[arg-type]


def test_stock_status_rules_in_order() -> None:
    assert status() == "normal"
    assert status(age_days=30) == "new"
    assert status(demand_class="new") == "new"
    assert status(days_of_cover=90.0) == "slow"
    assert status(days_of_cover=89.9) == "normal"
    quiet = np.concatenate([np.full(60, 2.0), np.zeros(60)])
    assert status(demand=quiet) == "non_moving"
    assert status(demand=quiet, on_hand=0.0) == "normal"  # nothing on the shelf to call dead
    away = np.ones(120, dtype=bool)
    away[60:] = False  # off the shelf the whole window
    assert status(demand=quiet, available=away) == "unverified"
    mostly = np.ones(120, dtype=bool)
    mostly[-18:] = False  # 70 percent of the window on the shelf
    assert status(demand=quiet, available=mostly) == "non_moving"
    mostly[-19:] = False
    assert status(demand=quiet, available=mostly) == "unverified"
    assert status(demand=quiet, is_seasonal=True, in_season=False) == "normal"
    assert status(demand=quiet, is_seasonal=True, in_season=True) == "non_moving"


def test_days_since_the_last_sale() -> None:
    demand = np.zeros(30)
    demand[10] = 1.0
    result = stock_status(
        demand=demand,
        available=np.ones(30, dtype=bool),
        as_of=AS_OF,
        start=AS_OF - timedelta(days=30),
        age_days=400,
        demand_class="smooth",
        on_hand=5.0,
        days_of_cover=None,
        is_seasonal=False,
        in_season=True,
        nonmoving_days=60,
        slow_cover_days=90,
    )
    assert result.days_since_sale == 19  # sold 20 days before the plan date, 19 full days since


def test_excess_quantity() -> None:
    assert excess_quantity(100.0, 60.0, 10.0) == 30.0
    assert excess_quantity(50.0, 60.0, 10.0) == 0.0
