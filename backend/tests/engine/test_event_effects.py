"""Event effect learning, the application gate and the multiplier timeline."""

from datetime import date, timedelta

import numpy as np
import pytest

from app.engine.calendar import CalendarEvent, delivery_padding, upcoming, window_mask
from app.engine.event_effects import (
    EffectRecord,
    PromoOccurrence,
    gate,
    learn_event_effects,
    learn_promotion_effects,
    multiplier_timeline,
    weighted_median,
)

START = date(2025, 1, 6)  # Monday
N_DAYS = 600
WEEK = np.array([0.9, 1.0, 1.0, 1.05, 1.1, 1.2, 0.75])


def event(
    slug: str,
    key: str,
    start: date,
    days: int = 5,
    *,
    kind: str = "festival",
    pre: int = 7,
    post: int = 3,
    delay: int = 0,
) -> CalendarEvent:
    return CalendarEvent(
        slug=slug,
        event_key=key,
        name=key,
        kind=kind,
        start=start,
        end=start + timedelta(days=days - 1),
        pre_days=pre,
        post_days=post,
        delay_days=delay,
    )


FEST_1 = event("fest-2025a", "fest", date(2025, 5, 10))
FEST_2 = event("fest-2025b", "fest", date(2025, 11, 1))


def history(
    n_products: int,
    effects: dict[tuple[date, date], float],
    *,
    seed: int = 7,
    base: float = 40.0,
    n_days: int = N_DAYS,
) -> np.ndarray:
    """Poisson demand with a weekday shape and a multiplier over the given date ranges."""
    rng = np.random.default_rng(seed)
    wd = (START.toordinal() - 1 + np.arange(n_days)) % 7
    lam = np.tile(base * WEEK[wd], (n_products, 1)) * rng.uniform(0.7, 1.3, (n_products, 1))
    for (a, b), mult in effects.items():
        lam[:, (a - START).days : (b - START).days + 1] *= mult
    return rng.poisson(lam).astype(np.float64)


def learn(
    y: np.ndarray,
    events: list[CalendarEvent],
    *,
    medical: bool = False,
    codes: np.ndarray | None = None,
    keys: list[str] | None = None,
) -> list[EffectRecord]:
    codes = np.zeros(y.shape[0], dtype=np.int64) if codes is None else codes
    return learn_event_effects(
        events=events,
        y=y,
        start=START,
        category_codes=codes,
        category_keys=keys or ["cat-a"],
        is_medical=medical,
    )


def pick(records: list[EffectRecord], key: str, window: str, cat: str = "cat-a") -> EffectRecord:
    return next(r for r in records if (r.event_key, r.window, r.category_key) == (key, window, cat))


def during(e: CalendarEvent) -> tuple[date, date]:
    return e.start, e.end


def test_planted_uplift_of_1_8_is_recovered_within_ten_percent() -> None:
    y = history(10, {during(FEST_1): 1.8, during(FEST_2): 1.8})
    record = pick(learn(y, [FEST_1, FEST_2]), "fest", "during")
    assert record.n_occurrences == 2
    assert record.n_products == 10
    assert record.evidence["raw_multiplier"] == pytest.approx(1.8, rel=0.10)
    # The shrunk value is 1 + (raw - 1) * n / (n + 0.5) = raw * 0.8 + 0.2 for two occurrences.
    assert record.multiplier == pytest.approx(
        1 + (record.evidence["raw_multiplier"] - 1) * 0.8, abs=0.002
    )
    assert record.is_applied
    assert record.label == "learned"
    assert record.confidence == "high"
    assert record.consistency is not None and record.consistency >= 0.75


def test_pure_noise_is_computed_but_never_applied() -> None:
    y = history(10, {})
    records = learn(y, [FEST_1, FEST_2])
    assert records, "the effect is still computed, so the insight screen can show the evidence"
    assert not any(r.is_applied for r in records)
    assert all(r.label == "not_enough_evidence" for r in records)
    assert all(r.confidence == "low" for r in records)


def test_one_occurrence_is_enough_for_a_normal_tenant() -> None:
    y = history(10, {during(FEST_1): 1.8})
    record = pick(learn(y, [FEST_1]), "fest", "during")
    assert record.n_occurrences == 1
    assert record.is_applied
    assert record.confidence == "medium"
    assert 1.4 < record.multiplier < 1.8  # shrunk by n / (n + 0.5) = 2/3


def test_medical_tenant_with_one_occurrence_is_not_applied() -> None:
    y = history(10, {during(FEST_1): 1.8})
    record = pick(learn(y, [FEST_1], medical=True), "fest", "during")
    assert not record.is_applied
    assert "medical_festival_rule" in record.evidence["blocked_by"]


def test_medical_tenant_with_two_consistent_occurrences_is_applied() -> None:
    y = history(10, {during(FEST_1): 1.8, during(FEST_2): 1.8})
    record = pick(learn(y, [FEST_1, FEST_2], medical=True), "fest", "during")
    assert record.is_applied


def test_medical_seasons_follow_the_normal_gate() -> None:
    season = event(
        "monsoon-2025", "monsoon", date(2025, 6, 10), days=112, kind="season", pre=0, post=0
    )
    y = history(10, {(season.start, season.end): 1.6})
    record = pick(learn(y, [season], medical=True), "monsoon", "during")
    assert record.is_applied
    assert record.label == "learned"


def test_a_category_needs_three_products() -> None:
    y = history(2, {during(FEST_1): 1.8})
    record = pick(learn(y, [FEST_1]), "fest", "during")
    assert not record.is_applied
    assert "too_few_products" in record.evidence["blocked_by"]


def test_one_day_festivals_cannot_apply_a_during_effect() -> None:
    one_day = event("eid-2025", "eid", date(2025, 5, 10), days=1)
    y = history(10, {during(one_day): 2.5})
    records = learn(y, [one_day])
    assert not pick(records, "eid", "during").is_applied
    assert "window_too_short" in pick(records, "eid", "during").evidence["blocked_by"]


def test_mixed_direction_products_are_not_consistent() -> None:
    y = history(10, {})
    # Half of the products rise 60 percent in the window, half fall 40 percent.
    a, b = (FEST_1.start - START).days, (FEST_1.end - START).days + 1
    y[:5, a:b] *= 1.6
    y[5:, a:b] *= 0.6
    record = pick(learn(y, [FEST_1]), "fest", "during")
    assert record.consistency is not None and record.consistency < 0.6
    assert not record.is_applied


def test_effects_are_learned_per_category() -> None:
    y = history(10, {})
    a, b = (FEST_1.start - START).days, (FEST_1.end - START).days + 1
    y[:5, a:b] *= 2.0
    codes = np.array([0] * 5 + [1] * 5)
    records = learn(y, [FEST_1], codes=codes, keys=["up", "flat"])
    assert pick(records, "fest", "during", "up").multiplier > 1.3
    assert pick(records, "fest", "during", "up").n_products == 5
    assert not pick(records, "fest", "during", "flat").is_applied


def test_occurrences_that_reach_past_the_history_are_ignored() -> None:
    late = event("fest-late", "late", START + timedelta(days=N_DAYS - 3))
    y = history(10, {})
    windows = {r.window for r in learn(y, [late]) if r.event_key == "late"}
    assert windows == {"pre"}  # the main days and the dip after it are not in the history yet


def test_baseline_needs_enough_days_before_the_event() -> None:
    early = event("fest-early", "early", START + timedelta(days=20), pre=5)
    assert not [r for r in learn(history(10, {}), [early]) if r.event_key == "early"]


def test_censored_days_are_not_learned_from() -> None:
    y = history(10, {during(FEST_1): 1.8})
    a = (FEST_1.start - START).days
    y[:, a : a + 1] = np.nan  # one of the five days was stocked out (80 percent are trusted)
    record = pick(learn(y, [FEST_1]), "fest", "during")
    assert record.evidence["raw_multiplier"] == pytest.approx(1.8, rel=0.10)


def test_products_with_too_few_trusted_days_in_the_window_are_dropped() -> None:
    y = history(10, {during(FEST_1): 1.8})
    a, b = (FEST_1.start - START).days, (FEST_1.end - START).days + 1
    y[:8, a : b - 1] = np.nan  # 8 products keep 1 of 5 days (20 percent)
    record = pick(learn(y, [FEST_1]), "fest", "during")
    assert record.n_products == 2
    assert not record.is_applied


def test_promotions_need_two_past_promotions_and_three_products() -> None:
    promo_1 = (date(2025, 4, 7), date(2025, 4, 13))
    promo_2 = (date(2025, 9, 1), date(2025, 9, 7))
    y_actual = history(10, {promo_1: 1.7, promo_2: 1.7})
    y_baseline = y_actual.copy()
    for a, b in (promo_1, promo_2):
        y_baseline[:, (a - START).days : (b - START).days + 1] = np.nan
    promos = [
        PromoOccurrence(promo_1[0], promo_1[1], None, "cat-a"),
        PromoOccurrence(promo_2[0], promo_2[1], None, "cat-a"),
    ]
    common = dict(
        y_baseline=y_baseline,
        y_actual=y_actual,
        start=START,
        category_codes=np.zeros(10, dtype=np.int64),
        category_keys=["cat-a"],
        events=[],
        is_medical=False,
    )
    records = learn_promotion_effects(promotions=promos, **common)  # type: ignore[arg-type]
    assert records[0].event_key == "promotion"
    assert records[0].is_applied
    assert records[0].evidence["raw_multiplier"] == pytest.approx(1.7, rel=0.10)
    one = learn_promotion_effects(promotions=promos[:1], **common)  # type: ignore[arg-type]
    assert not one[0].is_applied
    assert "too_few_occurrences" in one[0].evidence["blocked_by"]
    single = [
        PromoOccurrence(promo_1[0], promo_1[1], 0, None),
        PromoOccurrence(promo_2[0], promo_2[1], 0, None),
    ]
    alone = learn_promotion_effects(promotions=single, **common)  # type: ignore[arg-type]
    assert not alone[0].is_applied
    assert "too_few_products" in alone[0].evidence["blocked_by"]


def test_gate_reasons() -> None:
    ok = dict(
        multiplier=1.5,
        n_occurrences=2,
        n_products=5,
        consistency=0.9,
        window="pre",
        window_days=7,
        is_festival=True,
        is_medical=False,
    )
    assert gate(**ok) == []  # type: ignore[arg-type]
    assert gate(**{**ok, "multiplier": 1.1}) == ["shift_too_small"]  # type: ignore[arg-type]
    assert gate(**{**ok, "multiplier": 0.8}) == []  # type: ignore[arg-type]
    assert gate(**{**ok, "consistency": 0.5}) == ["not_consistent"]  # type: ignore[arg-type]
    assert gate(**{**ok, "is_medical": True, "n_occurrences": 1}) == ["medical_festival_rule"]  # type: ignore[arg-type]
    assert gate(**{**ok, "is_medical": True, "origin": "configured"}) == []  # type: ignore[arg-type]


def test_weighted_median() -> None:
    assert weighted_median(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 1.0])) == 2.0
    assert weighted_median(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 10.0])) == 3.0


def record(
    key: str, window: str, mult: float, *, origin: str = "learned", applied: bool = True
) -> EffectRecord:
    return EffectRecord(key, "cat-a", window, mult, origin, 1, 5, 0.9, {}, "medium", applied)


def test_timeline_applies_windows_and_picks_the_strongest_on_overlap() -> None:
    a = event("a-2026", "a", date(2026, 3, 10), days=3, pre=2, post=1)
    b = event("b-2026", "b", date(2026, 3, 11), days=3, pre=0, post=0)
    records = [
        record("a", "pre", 1.2),
        record("a", "during", 1.5),
        record("a", "post", 0.7),
        record("b", "during", 0.4),
        record("a", "during", 9.0, applied=False),
    ]
    start = date(2026, 3, 6)
    mult, keys = multiplier_timeline(records, [a, b], "cat-a", start, 10)
    # 6 Mar is outside, 8 and 9 Mar are the pre window of a, 10 Mar only a, 11 to 13 Mar overlap
    # a (1.5) and b (0.4): ln(1/0.4) is larger than ln(1.5), so b wins and nothing compounds.
    assert mult.tolist() == [1.0, 1.0, 1.2, 1.2, 1.5, 0.4, 0.4, 0.4, 1.0, 1.0]
    assert keys[4] == "a"
    assert keys[5] == "b"
    assert keys[0] is None
    # 14 Mar is a's post window but b still runs until 13 Mar.


def test_configured_effect_replaces_a_learned_one() -> None:
    a = event("a-2026", "a", date(2026, 3, 10), days=3, pre=0, post=0)
    records = [record("a", "during", 1.6), record("a", "during", 1.25, origin="configured")]
    mult, _ = multiplier_timeline(records, [a], "cat-a", date(2026, 3, 9), 5)
    assert mult.tolist() == [1.0, 1.25, 1.25, 1.25, 1.0]


def test_promotion_timeline_uses_the_category_or_the_product() -> None:
    records = [record("promotion", "during", 1.4)]
    promos = [
        PromoOccurrence(date(2026, 3, 11), date(2026, 3, 12), None, "cat-a"),
        PromoOccurrence(date(2026, 3, 14), date(2026, 3, 14), 3, None),
    ]
    mult, keys = multiplier_timeline(
        records, [], "cat-a", date(2026, 3, 10), 6, promos, product_index=3
    )
    assert mult.tolist() == [1.0, 1.4, 1.4, 1.0, 1.4, 1.0]
    assert keys[1] == "promotion"
    other, _ = multiplier_timeline(
        records, [], "cat-a", date(2026, 3, 10), 6, promos, product_index=9
    )
    assert other.tolist() == [1.0, 1.4, 1.4, 1.0, 1.0, 1.0]


def test_calendar_windows_and_helpers() -> None:
    e = event("a-2026", "a", date(2026, 3, 10), days=3, pre=2, post=1, delay=2)
    assert e.window("pre") == (date(2026, 3, 8), date(2026, 3, 9))
    assert e.window("post") == (date(2026, 3, 13), date(2026, 3, 13))
    assert e.anchor == date(2026, 3, 8)
    assert e.last_day == date(2026, 3, 13)
    assert event("s", "s", date(2026, 1, 1), kind="season", pre=0, post=0).window("pre") is None
    mask = window_mask([e], date(2026, 3, 7), 8)
    assert mask.tolist() == [False, True, True, True, True, True, True, False]
    assert delivery_padding([e], date(2026, 3, 1), 5) == 0
    assert delivery_padding([e], date(2026, 3, 1), 8) == 2
    assert upcoming([e], date(2026, 3, 1), 21) == [e]
    assert upcoming([e], date(2026, 2, 1), 21) == []
