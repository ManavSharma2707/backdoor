from datetime import date
from decimal import Decimal

import pytest

from app.engine.plan import Overrides
from app.engine.report_builder import day_text, days_text, m2, n_text, q3, units


@pytest.mark.parametrize(
    ("value", "text"),
    [(20.0, "20"), (12.4, "12"), (9.97, "10"), (2.5, "2.5"), (0.0, "0"), (3.02, "3")],
)
def test_n_text(value: float, text: str) -> None:
    assert n_text(value) == text


@pytest.mark.parametrize(
    ("days", "text"),
    [(6.9, "about 6 days"), (365.0, "about 365 days"), (366.0, "more than a year")],
)
def test_days_text(days: float, text: str) -> None:
    assert days_text(days) == text


def test_money_and_quantity_strings_are_fixed_point() -> None:
    assert m2(Decimal("12.345")) in {"12.34", "12.35"}
    assert m2(7.1) == "7.10"
    assert q3(1.23456789) == "1.235"
    assert q3(Decimal("2")) == "2.000"


def test_units_singular_only_at_one() -> None:
    assert units("pack", 1.0) != units("pack", 2.0)
    assert units("unknown_unit", 1.0) == "unknown_unit"
    assert units("unknown_unit", 3.0) == "unknown_units"


def test_day_text() -> None:
    assert day_text(date(2026, 10, 12)) == "12 Oct"


def test_empty_overrides() -> None:
    assert Overrides().is_empty
    assert not Overrides(demand_multiplier=1.2).is_empty
