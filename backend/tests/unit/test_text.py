import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.text import BANNED_WORDS, LONG_DASHES, contains_long_dash, humanize_text

EM = "—"
EN = "–"


def _banned_pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])", re.IGNORECASE)


def _banned_hits(text: str) -> list[str]:
    return [word for word in BANNED_WORDS if _banned_pattern(word).search(text)]


class TestDashes:
    def test_spaced_em_dash_becomes_comma(self) -> None:
        assert humanize_text(f"Stock is low {EM} order today.") == "Stock is low, order today."

    def test_tight_em_dash_becomes_comma(self) -> None:
        assert humanize_text(f"Stock{EM}order today") == "Stock, order today"

    def test_en_dash_between_numbers_becomes_to(self) -> None:
        assert humanize_text(f"Expires in 12{EN}18 months") == "Expires in 12 to 18 months"

    def test_spaced_en_dash_between_numbers_becomes_to(self) -> None:
        assert humanize_text(f"12 {EN} 18 packs") == "12 to 18 packs"

    def test_trailing_dash_is_dropped(self) -> None:
        assert humanize_text(f"Low stock {EM}") == "Low stock"

    def test_hyphen_and_minus_are_kept(self) -> None:
        assert humanize_text("A non-moving item, change -5") == "A non-moving item, change -5"

    @given(st.text())
    def test_no_long_dash_ever_survives(self, text: str) -> None:
        assert not contains_long_dash(humanize_text(text + EM + EN))


class TestBannedWords:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("We utilise the data", "We use the data"),
            ("Utilize the data", "Use the data"),
            ("Leverage your stock", "Use your stock"),
            ("See the insights", "See the numbers"),
            ("Simply save the bill", "Save the bill"),
            ("Save the bill easily", "Save the bill"),
            ("Welcome back. Your plan is ready.", "Your plan is ready."),
            ("Oops. That did not save.", "That did not save."),
        ],
    )
    def test_rewrites(self, raw: str, expected: str) -> None:
        assert humanize_text(raw) == expected

    def test_words_inside_other_words_are_left_alone(self) -> None:
        assert humanize_text("Adjust the smartphone setting") == "Adjust the smartphone setting"

    def test_hyphenated_compounds_are_left_alone(self) -> None:
        assert humanize_text("Just-in-time delivery") == "Just-in-time delivery"

    @pytest.mark.parametrize("word", BANNED_WORDS)
    def test_every_banned_word_is_removed(self, word: str) -> None:
        for sentence in (f"The {word} plan", f"{word.capitalize()} plan", f"Plan: {word.upper()}."):
            assert _banned_hits(humanize_text(sentence)) == [], sentence

    @given(
        st.lists(
            st.sampled_from([*BANNED_WORDS, "stock", "bill", "order", "the", ",", "."]), max_size=12
        )
    )
    def test_random_mixes_come_out_clean(self, words: list[str]) -> None:
        assert _banned_hits(humanize_text(" ".join(words))) == []


class TestTidying:
    def test_exclamation_marks_become_full_stops(self) -> None:
        assert humanize_text("Saved! Done!") == "Saved. Done."

    def test_emoji_are_removed(self) -> None:
        assert humanize_text("Saved \U0001f389 today") == "Saved today"

    def test_double_spaces_collapse(self) -> None:
        assert humanize_text("Two   spaces  here") == "Two spaces here"

    def test_space_before_punctuation_is_removed(self) -> None:
        assert humanize_text("Stock , order .") == "Stock, order."

    def test_loading_ellipsis_survives(self) -> None:
        assert humanize_text("Saving...") == "Saving..."

    def test_empty_string(self) -> None:
        assert humanize_text("") == ""

    def test_clean_text_is_unchanged(self) -> None:
        text = "Demand for the next 10 days is about 30 packs. You have 12 on the shelf."
        assert humanize_text(text) == text

    @given(st.text())
    def test_is_idempotent(self, text: str) -> None:
        once = humanize_text(text)
        assert humanize_text(once) == once

    def test_dash_constants(self) -> None:
        assert set(LONG_DASHES) == {EM, EN}
