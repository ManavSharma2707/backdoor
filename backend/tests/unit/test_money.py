from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core import money


class TestRounding:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.005", "1.01"),  # half up, not round-half-even
            ("1.004", "1.00"),
            ("2.675", "2.68"),
            ("0.125", "0.13"),
            ("-1.005", "-1.01"),
            ("10", "10.00"),
        ],
    )
    def test_round_money_is_half_up(self, raw: str, expected: str) -> None:
        assert money.round_money(raw) == Decimal(expected)

    def test_float_input_does_not_leak_binary_noise(self) -> None:
        assert money.round_money(2.675) == Decimal("2.68")

    def test_unit_price_keeps_four_places(self) -> None:
        assert money.round_unit_price("8.12345") == Decimal("8.1235")

    def test_quantity_keeps_three_places(self) -> None:
        assert money.round_qty("12.34549") == Decimal("12.345")
        assert money.round_qty("12.3455") == Decimal("12.346")

    def test_line_total_applies_discount_then_rounds(self) -> None:
        total = money.line_total(Decimal(3), Decimal("9.9950"), Decimal("1.00"))
        assert total == Decimal("28.99")

    def test_rejects_non_finite_values(self) -> None:
        for bad in ("NaN", "Infinity", float("inf")):
            with pytest.raises(ValueError, match="finite"):
                money.round_money(bad)

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="Not a decimal"):
            money.to_decimal("twelve")


class TestPaise:
    def test_round_trip(self) -> None:
        assert money.to_paise("182340.50") == 18_234_050
        assert money.from_paise(18_234_050) == Decimal("182340.50")

    @given(st.integers(min_value=-(10**12), max_value=10**12))
    def test_paise_round_trip_is_exact(self, paise: int) -> None:
        assert money.to_paise(money.from_paise(paise)) == paise


class TestJsonStrings:
    def test_money_has_two_decimals(self) -> None:
        assert money.money_str("182340") == "182340.00"
        assert money.money_str(Decimal("0.1") + Decimal("0.2")) == "0.30"

    def test_quantity_has_three_decimals(self) -> None:
        assert money.qty_str("12.5") == "12.500"

    def test_never_scientific_notation(self) -> None:
        assert "E" not in money.money_str(Decimal("1E+7"))
