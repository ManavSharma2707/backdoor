"""Replenishment: the worked example, MOQ, pack rounding, the expiry cap and the properties."""

import math
from datetime import date
from decimal import Decimal
from statistics import NormalDist

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engine.replenishment import (
    ReplenishInput,
    replenish,
    resolve_lead,
    safety_stock,
    spend,
)

AS_OF = date(2026, 10, 12)  # a Monday
Z95 = NormalDist().inv_cdf(0.95)


def inp(**overrides: object) -> ReplenishInput:
    base: dict[str, object] = {
        "forecast": np.full(28, 3.0),
        "lead_days": 3,
        "review_days": 7,
        "usable": 12.0,
        "incoming_confirmed": 5.0,
        "incoming_by_arrival": 5.0,
        "reserved": 0.0,
        "sigma_day": 4.0 / (Z95 * math.sqrt(10)),
        "service_level": 0.95,
        "min_stock_qty": 0.0,
        "pack_size": Decimal(10),
        "moq_units": Decimal(0),
    }
    base.update(overrides)
    return ReplenishInput(**base)  # type: ignore[arg-type]


def test_worked_example_from_the_testing_strategy() -> None:
    """Forecast 3 a day, P 10, usable 12, incoming 5, buffer 4, pack 10: raw 17, suggested 20."""
    r = replenish(inp())
    assert r.protection_days == 10
    assert r.demand_protection == pytest.approx(30.0)
    assert r.inventory_position == pytest.approx(17.0)
    assert r.safety_stock == pytest.approx(4.0)
    assert r.target_level == pytest.approx(34.0)
    assert r.raw_qty == pytest.approx(17.0)
    assert r.suggested_qty == 20.0
    assert r.packs == 2
    assert r.pack_excess_qty == pytest.approx(3.0)
    assert r.reasons == ["PACK_ROUNDING"]


def test_nothing_is_ordered_when_stock_covers_the_need() -> None:
    r = replenish(inp(usable=60.0))
    assert r.raw_qty == 0.0
    assert r.suggested_qty == 0.0
    assert r.packs == 0
    assert r.reasons == []


def test_minimum_stock_lifts_the_target() -> None:
    r = replenish(inp(usable=60.0, min_stock_qty=100.0))
    assert r.target_level == 100.0
    assert r.raw_qty == pytest.approx(35.0)
    assert r.suggested_qty == 40.0


def test_reserved_stock_is_not_available() -> None:
    assert replenish(inp(reserved=5.0)).raw_qty == pytest.approx(22.0)


def test_moq_applies_when_it_is_larger_than_the_need() -> None:
    r = replenish(inp(moq_units=Decimal(60), pack_size=Decimal(12)))
    assert r.suggested_qty == 60.0  # 5 packs of 12 meet a minimum of 60
    assert "MOQ_APPLIED" in r.reasons
    assert r.pack_excess_qty == pytest.approx(43.0)
    small = replenish(inp(moq_units=Decimal(5)))
    assert "MOQ_APPLIED" not in small.reasons


def test_pack_of_one_has_no_rounding_reason() -> None:
    r = replenish(inp(pack_size=Decimal(1)))
    assert r.suggested_qty == 17.0
    assert r.reasons == []
    assert r.pack_excess_qty == pytest.approx(0.0, abs=1e-6)


def test_float_noise_never_costs_an_extra_pack() -> None:
    r = replenish(
        inp(
            usable=2.0,
            incoming_confirmed=0.0,
            pack_size=Decimal("0.1"),
            sigma_day=0.0,
            forecast=np.full(28, 0.07),
        )
    )
    # Need 0.7 over 10 days minus 2 on hand is none. Use a case landing exactly on a pack.
    assert r.suggested_qty == 0.0
    exact = replenish(
        inp(
            usable=0.0,
            incoming_confirmed=0.0,
            sigma_day=0.0,
            forecast=np.full(28, 0.07),
            pack_size=Decimal("0.1"),
        )
    )
    assert exact.suggested_qty == pytest.approx(0.7)
    assert exact.packs == 7


def test_nearest_safe_rounds_down_only_when_covered_until_delivery() -> None:
    base = {
        "pack_size": Decimal(10),
        "usable": 20.0,
        "incoming_confirmed": 0.0,
        "incoming_by_arrival": 0.0,
        "sigma_day": 0.0,
        "pack_rounding": "nearest_safe",
    }
    covered = replenish(inp(**base, forecast=np.full(28, 3.0)))
    # Position 20, protection need 30, raw 10 -> exactly one pack, no excess to round down.
    assert covered.suggested_qty == 10.0
    forecast = np.full(28, 2.4)  # need 24 - 20 = 4, one pack leaves 6 excess, more than half
    safe = replenish(inp(**base, forecast=forecast))
    assert safe.suggested_qty == 0.0  # demand before delivery is 7.2, the 20 on hand covers it
    risky = replenish(inp(**{**base, "usable": 5.0}, forecast=np.full(28, 3.0)))
    assert risky.suggested_qty >= risky.raw_qty  # not covered, so it rounds up
    up = replenish(inp(**{**base, "pack_rounding": "up"}, forecast=forecast))
    assert up.suggested_qty == 10.0


def test_expiry_cap_limits_the_order_to_what_can_sell_before_expiry() -> None:
    # 60 percent of 20 days is 12 days of demand at 3 a day = 36, minus the position of 17.
    r = replenish(
        inp(
            is_batch_tracked=True,
            shelf_life_days=20,
            usable=12.0,
            forecast=np.full(28, 3.0),
            pack_size=Decimal(10),
        )
    )
    assert r.cap_qty == pytest.approx(19.0)
    assert r.suggested_qty == 20.0  # 19 rounds up to two packs, the order is already within it
    assert "EXPIRY_CAP" not in r.reasons
    tight = replenish(
        inp(
            is_batch_tracked=True,
            shelf_life_days=10,
            usable=12.0,
            forecast=np.full(28, 3.0),
        )
    )
    assert tight.cap_qty == pytest.approx(1.0)
    assert tight.suggested_qty == 10.0
    assert "EXPIRY_CAP" in tight.reasons


def test_expiry_cap_reduces_a_large_need() -> None:
    r = replenish(
        inp(
            is_batch_tracked=True,
            shelf_life_days=15,
            usable=0.0,
            incoming_confirmed=0.0,
            sigma_day=0.0,
            forecast=np.full(28, 5.0),
            pack_size=Decimal(10),
            review_days=21,
        )
    )
    # Protection 24 days = 120 needed, the cap is 9 days (15 * 0.6) = 45 units -> 5 packs of 10.
    assert r.raw_qty == pytest.approx(120.0)
    assert r.suggested_qty == 50.0
    assert "EXPIRY_CAP" in r.reasons


def test_expiry_cap_below_moq_orders_nothing_with_a_warning() -> None:
    r = replenish(
        inp(
            is_batch_tracked=True,
            shelf_life_days=15,
            usable=0.0,
            incoming_confirmed=0.0,
            sigma_day=0.0,
            forecast=np.full(28, 5.0),
            pack_size=Decimal(10),
            moq_units=Decimal(100),
            review_days=21,
        )
    )
    assert r.suggested_qty == 0.0
    assert r.packs == 0
    assert "MOQ_VS_SHELF_LIFE" in r.warnings
    assert "EXPIRY_CAP" in r.reasons


def test_untracked_products_ignore_the_shelf_life() -> None:
    r = replenish(inp(is_batch_tracked=False, shelf_life_days=5))
    assert r.cap_qty is None


def test_safety_stock_uses_the_normal_quantile() -> None:
    assert safety_stock(2.0, 9, 0.95) == pytest.approx(Z95 * 2.0 * 3.0)
    assert safety_stock(0.0, 9, 0.95) == 0.0
    assert safety_stock(2.0, 0, 0.95) == 0.0
    assert safety_stock(2.0, 9, 5.0) == safety_stock(2.0, 9, 0.999)  # service level is clipped


def test_demand_beyond_the_horizon_continues_at_the_recent_average() -> None:
    forecast = np.concatenate([np.full(14, 1.0), np.full(14, 4.0)])
    r = replenish(
        inp(
            forecast=forecast,
            lead_days=10,
            review_days=25,
            usable=0.0,
            incoming_confirmed=0.0,
            sigma_day=0.0,
        )
    )
    assert r.demand_protection == pytest.approx(14 + 14 * 4 + 7 * 4)


def test_spend_in_whole_paise() -> None:
    assert spend(20.0, Decimal("8.3333")) == Decimal("166.67")
    assert spend(0.0, Decimal("8")) == Decimal("0.00")
    assert spend(5.0, None) is None


def test_lead_time_moves_to_the_delivery_weekday_and_adds_padding() -> None:
    # Monday plan, lead time 2 days -> Wednesday, supplier delivers Tuesday and Friday -> Friday.
    r = resolve_lead(AS_OF, None, 2, 3, (2, 5))
    assert (r.base_days, r.source, r.effective_days, r.total_days) == (2, "supplier_default", 4, 4)
    assert r.arrival == date(2026, 10, 16)
    padded = resolve_lead(AS_OF, 1, 2, 3, None, padding_days=2)
    assert (padded.base_days, padded.source, padded.total_days) == (1, "product_term", 3)
    assert not padded.is_assumed
    assumed = resolve_lead(AS_OF, None, None, 3, None)
    assert assumed.source == "business_default"
    assert assumed.is_assumed
    assert assumed.arrival == date(2026, 10, 15)


finite = st.floats(min_value=0, max_value=500, allow_nan=False)


@settings(max_examples=250, deadline=None)
@given(
    rate=st.floats(min_value=0, max_value=40),
    lead=st.integers(0, 10),
    review=st.integers(1, 21),
    usable=finite,
    incoming=finite,
    reserved=st.floats(min_value=0, max_value=50),
    sigma=st.floats(min_value=0, max_value=30),
    pack=st.sampled_from([1, 2, 6, 10, 12, 48]),
    moq=st.sampled_from([0, 0, 5, 24, 100]),
    min_stock=st.floats(min_value=0, max_value=60),
    shelf=st.one_of(st.none(), st.integers(5, 400)),
    mode=st.sampled_from(["up", "nearest_safe"]),
)
def test_replenishment_properties(
    rate: float,
    lead: int,
    review: int,
    usable: float,
    incoming: float,
    reserved: float,
    sigma: float,
    pack: int,
    moq: int,
    min_stock: float,
    shelf: int | None,
    mode: str,
) -> None:
    r = replenish(
        ReplenishInput(
            forecast=np.full(28, rate),
            lead_days=lead,
            review_days=review,
            usable=usable,
            incoming_confirmed=incoming,
            incoming_by_arrival=incoming,
            reserved=reserved,
            sigma_day=sigma,
            service_level=0.95,
            min_stock_qty=min_stock,
            pack_size=Decimal(pack),
            moq_units=Decimal(moq),
            shelf_life_days=shelf,
            is_batch_tracked=shelf is not None,
            pack_rounding=mode,
        )
    )
    assert r.suggested_qty >= 0
    assert r.raw_qty >= 0
    # A multiple of the pack size, always.
    assert (Decimal(repr(round(r.suggested_qty, 6))) % Decimal(pack)) == 0
    assert r.packs * pack == pytest.approx(r.suggested_qty)
    if r.suggested_qty > 0:
        assert r.suggested_qty >= moq  # the minimum order is always met when anything is ordered
    if mode == "up" and "EXPIRY_CAP" not in r.reasons and r.raw_qty > 0 and not r.warnings:
        assert r.suggested_qty >= r.raw_qty - 1e-6  # never short of the need
    if r.raw_qty == 0:
        assert r.suggested_qty == 0
    if r.pack_excess_qty > 0:
        assert r.pack_excess_qty < max(pack, moq + pack) + 1e-6 or "EXPIRY_CAP" in r.reasons
