"""Learning festival, season and promotion effects from history (`engine-spec.md` section 7).

An effect is a multiplier per tenant, category, event and window. It is learned as the ratio of
what sold in the window to what a weekday profile fitted before the event expected, shrunk for
the number of occurrences, and applied only when the evidence passes the gate.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import NormalDist
from typing import Any

import numpy as np

from app.engine.calendar import CalendarEvent, window_mask
from app.engine.constants import (
    EFFECT_BASELINE_WEEKS,
    EFFECT_CLIP_HIGH,
    EFFECT_CLIP_LOW,
    EFFECT_DEVIATION,
    EFFECT_FDR,
    EFFECT_MIN_BASELINE_DAYS,
    EFFECT_MIN_CONSISTENCY,
    EFFECT_MIN_DURING_DAYS,
    EFFECT_MIN_PRODUCTS,
    EFFECT_MIN_SHIFT,
    EFFECT_MIN_TRUSTED_SHARE,
    EFFECT_SHRINK_K,
    HIGH_EFFECT_CONSISTENCY,
    MEDICAL_MIN_CONSISTENCY,
    MEDICAL_MIN_OCCURRENCES,
    PROMO_MIN_OCCURRENCES,
    PROMOTION_KEY,
    WEEKDAY_SHRINK_K,
)
from app.engine.types import BoolArray, Confidence, FloatArray, IntArray


@dataclass(frozen=True)
class EffectRecord:
    event_key: str
    category_key: str
    window: str
    multiplier: float
    origin: str
    n_occurrences: int
    n_products: int
    consistency: float | None
    evidence: dict[str, Any]
    confidence: Confidence
    is_applied: bool

    @property
    def label(self) -> str:
        if not self.is_applied:
            return "not_enough_evidence"
        return "set_by_you" if self.origin == "configured" else "learned"


@dataclass(frozen=True)
class PromoOccurrence:
    """A past or planned promotion. Exactly one of `product_index` and `category_key` is set."""

    start: date
    end: date
    product_index: int | None
    category_key: str | None


@dataclass
class _Occurrence:
    slug: str
    start: date
    end: date
    ratio: float
    n_products: int
    consistency: float
    volume: float
    dispersion: float


@dataclass(frozen=True)
class Baseline:
    """A weekday profile fitted on the days before an event, per product.

    `disp_num` and `disp_den` give the dispersion of the demand around the profile: the squared
    residuals (corrected for the fitted parameters) and the expected demand, both summed over the
    baseline days. Their ratio is 1 for Poisson demand and larger for noisier demand.
    """

    level: FloatArray
    idx: FloatArray
    share: FloatArray
    count: IntArray
    disp_num: FloatArray
    disp_den: FloatArray


def baseline_profile(y: FloatArray, lo: int, hi: int, start: date, excluded: BoolArray) -> Baseline:
    """Level, shrunk weekday indices, trusted share and dispersion per product over the days
    `lo..hi` of `y` (shape P by T), ignoring excluded days."""
    seg = y[:, lo:hi].copy()
    keep = ~excluded[lo:hi]
    seg[:, ~keep] = np.nan
    valid = ~np.isnan(seg)
    count = valid.sum(axis=1)
    safe = np.where(valid, seg, 0.0)
    level = np.divide(safe.sum(axis=1), count, out=np.zeros(len(count)), where=count > 0)
    base = start.toordinal() - 1 + lo
    wd = (base + np.arange(hi - lo)) % 7
    idx = np.ones((y.shape[0], 7), dtype=np.float64)
    for d in range(7):
        sel = wd == d
        n_d = valid[:, sel].sum(axis=1)
        total = safe[:, sel].sum(axis=1)
        mean_d = np.divide(total, n_d, out=np.zeros(len(n_d)), where=n_d > 0)
        raw = np.divide(mean_d, level, out=np.ones(len(level)), where=level > 0)
        shrunk = 1.0 + (raw - 1.0) * n_d / (n_d + WEEKDAY_SHRINK_K)
        idx[:, d] = np.where((n_d > 0) & (level > 0), shrunk, 1.0)
    usable_days = int(keep.sum())
    share = count / usable_days if usable_days else np.zeros(len(count))
    expected = level[:, None] * idx[:, wd]
    resid = np.where(valid, (seg - expected) ** 2, 0.0)
    df = np.maximum(count - 7, 1)
    disp_num = resid.sum(axis=1) * count / df
    disp_den = np.where(valid, expected, 0.0).sum(axis=1)
    return Baseline(
        level, idx, share.astype(np.float64), count.astype(np.int64), disp_num, disp_den
    )


def weighted_median(values: FloatArray, weights: FloatArray) -> float:
    order = np.argsort(values, kind="stable")
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    return float(v[int(np.searchsorted(cum, cum[-1] / 2.0))])


def _category_ratio(ratios: FloatArray, weights: FloatArray) -> tuple[float, float]:
    """Weighted median ratio and the volume share of products that agree with its direction."""
    median = weighted_median(ratios, weights)
    sign = np.sign(median - 1.0)
    if sign == 0:
        return median, 0.0
    agree = (np.sign(ratios - 1.0) == sign) & (np.abs(ratios - 1.0) > EFFECT_DEVIATION)
    return median, float(weights[agree].sum() / weights.sum())


def _measure(
    y: FloatArray,
    base_fit: Baseline,
    usable: BoolArray,
    lo: int,
    hi: int,
    start: date,
    category_codes: IntArray,
    n_categories: int,
) -> dict[int, tuple[float, int, float, float, float]]:
    """Per category code: ratio, usable products, consistency, baseline volume and dispersion
    for the days `lo..hi` (end exclusive). Products need 70 percent trusted days in the window."""
    level, idx = base_fit.level, base_fit.idx
    base = start.toordinal() - 1 + lo
    wd = (base + np.arange(hi - lo)) % 7
    seg = y[:, lo:hi]
    valid = ~np.isnan(seg)
    expected = level[:, None] * idx[:, wd]
    actual_sum = np.where(valid, seg, 0.0).sum(axis=1)
    base_sum = np.where(valid, expected, 0.0).sum(axis=1)
    share = valid.sum(axis=1) / max(hi - lo, 1)
    ok = usable & (share >= EFFECT_MIN_TRUSTED_SHARE) & (base_sum > 0)
    out: dict[int, tuple[float, int, float, float, float]] = {}
    for code in range(n_categories):
        sel = ok & (category_codes == code)
        if not sel.any():
            continue
        ratios = actual_sum[sel] / base_sum[sel]
        weights = base_sum[sel]
        median, consistency = _category_ratio(ratios, weights)
        den = float(base_fit.disp_den[sel].sum())
        dispersion = max(float(base_fit.disp_num[sel].sum()) / den, 1.0) if den > 0 else 1.0
        out[code] = (median, int(sel.sum()), consistency, float(weights.sum()), dispersion)
    return out


def gate(
    *,
    multiplier: float,
    n_occurrences: int,
    n_products: int,
    consistency: float,
    window: str,
    window_days: int,
    is_festival: bool,
    is_medical: bool,
    origin: str = "learned",
    is_promotion: bool = False,
) -> list[str]:
    """Reasons an effect may not be applied. An empty list means it passes."""
    reasons: list[str] = []
    min_occurrences = PROMO_MIN_OCCURRENCES if is_promotion else 1
    if n_occurrences < min_occurrences:
        reasons.append("too_few_occurrences")
    if n_products < EFFECT_MIN_PRODUCTS:
        reasons.append("too_few_products")
    if window == "during" and not is_promotion and window_days < EFFECT_MIN_DURING_DAYS:
        reasons.append("window_too_short")
    if abs(multiplier - 1.0) < EFFECT_MIN_SHIFT:
        reasons.append("shift_too_small")
    if consistency < EFFECT_MIN_CONSISTENCY:
        reasons.append("not_consistent")
    if (
        is_medical
        and is_festival
        and origin != "configured"
        and (n_occurrences < MEDICAL_MIN_OCCURRENCES or consistency < MEDICAL_MIN_CONSISTENCY)
    ):
        reasons.append("medical_festival_rule")
    return reasons


def _combine(
    pool: list[_Occurrence],
    *,
    event_key: str,
    window: str,
    window_days: int,
    category_key: str,
    is_festival: bool,
    is_medical: bool,
    is_promotion: bool = False,
) -> EffectRecord:
    n = len(pool)
    mean_log = sum(math.log(max(o.ratio, 1e-6)) for o in pool) / n
    raw = math.exp(mean_log)
    shrunk = 1.0 + (raw - 1.0) * n / (n + EFFECT_SHRINK_K)
    multiplier = min(max(shrunk, EFFECT_CLIP_LOW), EFFECT_CLIP_HIGH)
    consistency = sum(o.consistency for o in pool) / n
    n_products = min(o.n_products for o in pool)
    volume = sum(o.volume for o in pool)
    # Test against "no effect": under that hypothesis the window total has variance
    # dispersion * expected, so each occurrence gives z = |ratio - 1| * sqrt(expected / dispersion).
    # Occurrences are combined with Stouffer's method.
    z_each = [abs(o.ratio - 1.0) * math.sqrt(o.volume / o.dispersion) for o in pool]
    z_score = sum(z_each) / math.sqrt(n)
    p_value = round(2.0 * (1.0 - NormalDist().cdf(z_score)), 6)
    reasons = gate(
        multiplier=multiplier,
        n_occurrences=n,
        n_products=n_products,
        consistency=consistency,
        window=window,
        window_days=window_days,
        is_festival=is_festival,
        is_medical=is_medical,
        is_promotion=is_promotion,
    )
    applied = not reasons
    confidence: Confidence = "low"
    if applied:
        confidence = "high" if n >= 2 and consistency >= HIGH_EFFECT_CONSISTENCY else "medium"
    evidence: dict[str, Any] = {
        "raw_multiplier": round(raw, 4),
        "baseline_volume": round(volume, 2),
        "z_score": round(z_score, 2),
        "p_value": p_value,
        "window_days": window_days,
        "occurrences": [
            {
                "slug": o.slug,
                "start": o.start.isoformat(),
                "end": o.end.isoformat(),
                "ratio": round(o.ratio, 4),
                "products": o.n_products,
                "consistency": round(o.consistency, 4),
            }
            for o in pool
        ],
        "blocked_by": reasons,
    }
    return EffectRecord(
        event_key=event_key,
        category_key=category_key,
        window=window,
        multiplier=round(multiplier, 3),
        origin="learned",
        n_occurrences=n,
        n_products=n_products,
        consistency=round(consistency, 3),
        evidence=evidence,
        confidence=confidence,
        is_applied=applied,
    )


def apply_fdr(records: list[EffectRecord]) -> list[EffectRecord]:
    """Keep an effect only when it survives a false discovery rate control over all the effects
    learned together (Benjamini and Hochberg, 10 percent).

    A tenant has hundreds of event, category and window combinations. Tested one by one at the
    usual 5 percent level, dozens would pass by chance alone. Controlling the expected share of
    false effects among those applied lets strong effects through and drops weak ones, however
    many tests were run.
    """
    m = len(records)
    if m == 0:
        return records
    ranked = sorted(range(m), key=lambda i: records[i].evidence["p_value"])
    cutoff = 0.0
    for rank, i in enumerate(ranked, start=1):
        if records[i].evidence["p_value"] <= EFFECT_FDR * rank / m:
            cutoff = records[i].evidence["p_value"]
    out: list[EffectRecord] = []
    for record in records:
        if record.is_applied and record.evidence["p_value"] > cutoff:
            blocked = [*record.evidence["blocked_by"], "not_significant"]
            record = replace(
                record,
                is_applied=False,
                confidence="low",
                evidence={**record.evidence, "blocked_by": blocked},
            )
        out.append(record)
    return out


def learn_event_effects(
    *,
    events: Sequence[CalendarEvent],
    y: FloatArray,
    start: date,
    category_codes: IntArray,
    category_keys: Sequence[str],
    is_medical: bool,
) -> list[EffectRecord]:
    """Effects of every calendar event for every category, from the occurrences that lie fully
    inside the history `y` (products by days, NaN where a day must not be learned from)."""
    n_days = y.shape[1]
    festival = window_mask(events, start, n_days, kinds=("festival",))
    history_end = start + timedelta(days=n_days)
    pools: dict[tuple[str, str, int], list[_Occurrence]] = defaultdict(list)
    spans: dict[tuple[str, str], int] = {}
    kinds: dict[str, str] = {}
    n_categories = len(category_keys)

    for event in sorted(events, key=lambda e: e.start):
        kinds[event.event_key] = event.kind
        anchor = (event.anchor - start).days
        lo = max(anchor - EFFECT_BASELINE_WEEKS * 7, 0)
        if anchor >= n_days or anchor - lo < EFFECT_MIN_BASELINE_DAYS:
            continue
        fit = baseline_profile(y, lo, anchor, start, festival)
        usable = (fit.share >= EFFECT_MIN_TRUSTED_SHARE) & (fit.level > 0)
        for window, first, last in event.spans():
            if last >= history_end or first < start:
                continue
            a, b = (first - start).days, (last - start).days + 1
            spans[(event.event_key, window)] = max(
                spans.get((event.event_key, window), 0), (last - first).days + 1
            )
            for code, (ratio, n_prod, consistency, volume, disp) in _measure(
                y, fit, usable, a, b, start, category_codes, n_categories
            ).items():
                pools[(event.event_key, window, code)].append(
                    _Occurrence(event.slug, first, last, ratio, n_prod, consistency, volume, disp)
                )

    records: list[EffectRecord] = []
    for (key, window, code), pool in sorted(pools.items()):
        records.append(
            _combine(
                pool,
                event_key=key,
                window=window,
                window_days=spans[(key, window)],
                category_key=category_keys[code],
                is_festival=kinds[key] == "festival",
                is_medical=is_medical,
            )
        )
    return apply_fdr(records)


def learn_promotion_effects(
    *,
    promotions: Sequence[PromoOccurrence],
    y_baseline: FloatArray,
    y_actual: FloatArray,
    start: date,
    category_codes: IntArray,
    category_keys: Sequence[str],
    events: Sequence[CalendarEvent],
    is_medical: bool,
) -> list[EffectRecord]:
    """Uplift on promotion days per category. `y_baseline` has promotion days removed (the
    training series), `y_actual` keeps them. Needs two or more past promotions in a category."""
    n_days = y_baseline.shape[1]
    festival = window_mask(events, start, n_days, kinds=("festival",))
    history_end = start + timedelta(days=n_days)
    pools: dict[str, list[_Occurrence]] = defaultdict(list)
    spans: dict[str, int] = {}
    code_of = {key: i for i, key in enumerate(category_keys)}

    for promo in sorted(promotions, key=lambda p: p.start):
        if promo.end >= history_end or promo.start < start:
            continue
        anchor = (promo.start - start).days
        lo = max(anchor - EFFECT_BASELINE_WEEKS * 7, 0)
        if anchor >= n_days or anchor - lo < EFFECT_MIN_BASELINE_DAYS:
            continue
        fit = baseline_profile(y_baseline, lo, anchor, start, festival)
        usable = (fit.share >= EFFECT_MIN_TRUSTED_SHARE) & (fit.level > 0)
        if promo.product_index is not None:
            only = np.zeros(len(usable), dtype=np.bool_)
            only[promo.product_index] = True
            usable = usable & only
        elif promo.category_key in code_of:
            usable = usable & (category_codes == code_of[promo.category_key])
        else:
            continue
        a, b = anchor, (promo.end - start).days + 1
        measured = _measure(y_actual, fit, usable, a, b, start, category_codes, len(category_keys))
        for code, (ratio, n_prod, consistency, volume, disp) in measured.items():
            key = category_keys[code]
            pools[key].append(
                _Occurrence(
                    f"promotion {promo.start.isoformat()}",
                    promo.start,
                    promo.end,
                    ratio,
                    n_prod,
                    consistency,
                    volume,
                    disp,
                )
            )
            spans[key] = max(spans.get(key, 0), (promo.end - promo.start).days + 1)

    return apply_fdr(
        [
            _combine(
                pool,
                event_key=PROMOTION_KEY,
                window="during",
                window_days=spans[key],
                category_key=key,
                is_festival=False,
                is_medical=is_medical,
                is_promotion=True,
            )
            for key, pool in sorted(pools.items())
        ]
    )


def effective_records(records: Sequence[EffectRecord]) -> dict[tuple[str, str, str], EffectRecord]:
    """The applied record per (event, category, window). An owner set effect replaces a learned
    one for the same key."""
    chosen: dict[tuple[str, str, str], EffectRecord] = {}
    for record in records:
        if not record.is_applied:
            continue
        key = (record.event_key, record.category_key, record.window)
        current = chosen.get(key)
        if current is None or (record.origin == "configured" and current.origin != "configured"):
            chosen[key] = record
    return chosen


def multiplier_timeline(
    records: Sequence[EffectRecord],
    events: Sequence[CalendarEvent],
    category_key: str,
    start: date,
    n_days: int,
    promotions: Sequence[PromoOccurrence] = (),
    product_index: int | None = None,
) -> tuple[FloatArray, list[str | None]]:
    """Multiplier and event key per day for one category. On a day covered by several windows
    the one furthest from 1 (largest `abs(ln m)`) is used, they never compound."""
    mult = np.ones(n_days, dtype=np.float64)
    keys: list[str | None] = [None] * n_days
    best = np.zeros(n_days, dtype=np.float64)
    applied = effective_records(records)

    def put(a: int, b: int, m: float, key: str) -> None:
        strength = abs(math.log(m))
        for d in range(max(a, 0), min(b, n_days - 1) + 1):
            if strength > best[d]:
                best[d], mult[d], keys[d] = strength, m, key

    for event in events:
        for window, first, last in event.spans():
            record = applied.get((event.event_key, category_key, window))
            if record is not None:
                put((first - start).days, (last - start).days, record.multiplier, event.event_key)
    promo_record = applied.get((PROMOTION_KEY, category_key, "during"))
    if promo_record is not None:
        for promo in promotions:
            hits = promo.category_key == category_key or (
                promo.product_index is not None and promo.product_index == product_index
            )
            if hits:
                put(
                    (promo.start - start).days,
                    (promo.end - start).days,
                    promo_record.multiplier,
                    PROMOTION_KEY,
                )
    return mult, keys
