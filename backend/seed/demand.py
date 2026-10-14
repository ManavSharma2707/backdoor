"""True demand: what customers would buy if shelves were never empty.

lambda[p,t] = base * weekday * monthday * season * event * promo * price * trend * step * ramp
demand[p,t] ~ NegBin(mean = lambda, size = nb_size), zero inflated for intermittent products.
Everything is vectorised over products x days. The same arrays feed `synthetic_true_demand`.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.jobs.reference_data import CALENDAR_EVENTS, EventRow
from seed.model import Catalog
from seed.pricing import Timelines
from seed.rng import stream
from seed.scenarios import ScenarioPlan
from seed.traits import (
    AFTER_DIP_DAYS,
    AFTER_DIP_LEVEL,
    FMCG_EVENTS,
    FMCG_SEASONS,
    FMCG_TRAITS,
    MAJOR_EVENTS,
    MED_TRAITS,
    REDUCED_HOURS_FACTOR,
    TENANT_EVENT_BOOST,
    WEEKDAY_PROFILES,
)

SEASON_KEYS = ("summer", "monsoon", "winter")
# Single days with reduced trading hours: Diwali Lakshmi Puja evening and Holi afternoon.
REDUCED_HOURS_DAYS: dict[date, str] = {date(2025, 10, 20): "diwali", date(2026, 3, 4): "holi"}
LINE_QTY_CONTINUE = {"fmcg": 0.55, "medical": 0.4}  # chance a further unit starts a new bill line


@dataclass
class Demand:
    true_demand: np.ndarray  # int32 [n, T]
    lam: np.ndarray  # float32 [n, T] expected demand
    event_mult: np.ndarray  # float32 [n, T]
    promo_mult: np.ndarray  # float32 [n, T]
    scale_factor: float
    dates: list[date]


def season_indicators(dates: list[date]) -> dict[str, np.ndarray]:
    out = {k: np.zeros(len(dates)) for k in SEASON_KEYS}
    index = {d: i for i, d in enumerate(dates)}
    for ev in CALENDAR_EVENTS:
        if ev.kind != "season" or ev.event_key not in out:
            continue
        d = max(ev.start, dates[0])
        while d <= min(ev.end, dates[-1]):
            out[ev.event_key][index[d]] = 1.0
            d += timedelta(days=1)
    kernel = np.ones(9) / 9.0
    return {k: np.convolve(np.pad(v, 4, mode="edge"), kernel, mode="valid") for k, v in out.items()}


def event_curve(
    ev: EventRow, dates: list[date], pre_peak: float, during: float, post: float
) -> np.ndarray:
    """Multiplier path for one occurrence: ramp up, flat peak, dip and recover, short hangover."""
    curve = np.ones(len(dates))
    first = dates[0]
    for i, d in enumerate(dates):
        if d < ev.start:
            gap = (ev.start - d).days
            if gap <= ev.pre:
                curve[i] = 1.0 + (pre_peak - 1.0) * (ev.pre - gap + 1) / ev.pre
        elif d <= ev.end:
            curve[i] = during
        else:
            k = (d - ev.end).days
            if k <= ev.post:
                curve[i] = post + (1.0 - post) * (k - 1) / ev.post
            elif k <= ev.post + AFTER_DIP_DAYS and ev.event_key in MAJOR_EVENTS and during >= 1.3:
                curve[i] = AFTER_DIP_LEVEL
    del first
    return curve


def monthday_factor(kind: str, dates: list[date], ration_peak: float) -> np.ndarray:
    dom = np.array([d.day for d in dates])
    if kind == "ration":
        return np.where(dom <= 7, ration_peak, np.where(dom <= 20, 0.9, 0.8))
    if kind == "chronic":
        return np.where(dom <= 10, 1.4, 0.9)
    if kind == "salary":
        return np.where(dom <= 7, 1.12, 1.0)
    return np.ones(len(dates))


def _event_matrix(catalog: Catalog, plan: ScenarioPlan, dates: list[date]) -> np.ndarray:
    n = len(catalog.products)
    ev = np.ones((n, len(dates)))
    profile = catalog.profile
    by_cat: dict[str, list[int]] = {}
    for p in catalog.products:
        by_cat.setdefault(p.category, []).append(p.index)
    if not profile.is_medical:
        boost = TENANT_EVENT_BOOST.get(profile.key, {})
        no_effect = set(plan.no_effect_pairs)
        for occurrence in CALENDAR_EVENTS:
            table = FMCG_EVENTS.get(occurrence.event_key)
            if table is None or occurrence.kind != "festival":
                continue
            if occurrence.end < dates[0] - timedelta(days=30) or occurrence.start > dates[-1]:
                continue
            for slug, (pre_peak, during, post) in table.items():
                if (occurrence.event_key, slug) in no_effect or slug not in by_cat:
                    continue
                strength = boost.get(occurrence.event_key, 1.0)
                curve = event_curve(
                    occurrence,
                    dates,
                    1 + (pre_peak - 1) * strength,
                    1 + (during - 1) * strength,
                    post,
                )
                for pi in by_cat[slug]:
                    jit = catalog.products[pi].event_jitter
                    ev[pi, :] *= 1.0 + (curve - 1.0) * jit
    elif plan.spurious is not None:
        event_key, slug, mult = plan.spurious
        occurrence = next(
            e for e in CALENDAR_EVENTS if e.event_key == event_key and e.start.year == 2025
        )
        curve = event_curve(occurrence, dates, 1 + (mult - 1) * 0.5, mult, 0.95)
        for pi in by_cat.get(slug, []):
            ev[pi, :] *= curve
    return np.clip(ev, 0.2, 4.0)


def _promo_matrix(catalog: Catalog, tl: Timelines, n_days: int) -> np.ndarray:
    n = len(catalog.products)
    pm = np.ones((n, n_days))
    profile = catalog.profile
    strength = 1.15 if profile.key == "fmcg_b" else (0.35 if profile.is_medical else 1.0)
    by_cat: dict[str, list[int]] = {}
    for p in catalog.products:
        by_cat.setdefault(p.category, []).append(p.index)
    for promo in tl.promotions:
        members = [promo.product] if promo.product is not None else by_cat[promo.category or ""]
        up = 1.0 + (promo.uplift - 1.0) * strength
        post_end = min(n_days, promo.end_idx + 6)
        for pi in members:
            pm[pi, promo.start_idx : promo.end_idx + 1] *= up
            pm[pi, promo.end_idx + 1 : post_end] *= 0.8
    return pm


def build_lambda(
    catalog: Catalog, plan: ScenarioPlan, tl: Timelines, dates: list[date]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    profile = catalog.profile
    n, t_days = len(catalog.products), len(dates)
    wd = np.array([d.weekday() for d in dates])
    seasons = season_indicators(dates)
    ev = _event_matrix(catalog, plan, dates)
    pm = _promo_matrix(catalog, tl, t_days)
    days = np.arange(t_days)
    lam = np.empty((n, t_days))
    for p in catalog.products:
        if profile.is_medical:
            mt = MED_TRAITS[p.category]
            weekday = np.array(WEEKDAY_PROFILES[mt.weekday])[wd]
            monthday = monthday_factor(mt.monthday, dates, 1.0)
            season = np.ones(t_days)
            for key, value in mt.season.items():
                season = season + (value - 1.0) * seasons[key]
        else:
            ft = FMCG_TRAITS[p.category]
            weekday = np.array(WEEKDAY_PROFILES[ft.weekday])[wd]
            ration_peak = 1.5 + (p.event_jitter - 0.85) / 0.30 * 0.5
            monthday = monthday_factor(ft.monthday, dates, ration_peak)
            season = np.ones(t_days)
            season_key = ft.season
            if p.item_tag == "noodles":
                season_key = "monsoon_snack"
            elif p.item_tag == "ghee":
                season_key = "oil"
            for key, value in FMCG_SEASONS[season_key].items():
                season = season + (value - 1.0) * seasons[key]
        price_ratio = tl.sell[p.index, :] / float(tl.sell[p.index, 0])
        price_effect = np.clip(price_ratio ** (-p.elasticity), 0.4, 3.0)
        trend = (1.0 + p.trend_pct_year / 100.0) ** ((days - t_days / 2.0) / 365.0)
        lam[p.index, :] = p.base_rate * weekday * monthday * season * price_effect * trend
    for pi, day, factor in plan.step_changes:
        lam[pi, day:] *= factor
    for pi, day in plan.discontinue_idx.items():
        lam[pi, day:] = 0.0
    for pi, day in plan.launch_idx.items():
        ramp = np.clip(0.4 + 0.6 * (days - day) / 21.0, 0.0, 1.0)
        lam[pi, :] = np.where(days < day, 0.0, lam[pi, :] * ramp)
    reduced = np.ones(t_days)
    for i, d in enumerate(dates):
        key = REDUCED_HOURS_DAYS.get(d)
        if key and (not profile.is_medical or key == "diwali"):
            reduced[i] = REDUCED_HOURS_FACTOR if not profile.is_medical else 0.6
    lam = lam * ev * pm * reduced
    return lam, ev, pm


def _draw(lam: np.ndarray, q: np.ndarray, size: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    active = rng.random(lam.shape) < q[:, None]
    mean = np.where(q[:, None] > 0, lam / q[:, None], 0.0)
    mean = np.maximum(mean, 1e-9)
    r = size[:, None]
    p = r / (r + mean)
    draws = rng.negative_binomial(r, p)
    return np.where(active, draws, 0).astype(np.int32)


def _lines_of(units: np.ndarray, kind: str) -> float:
    cont = LINE_QTY_CONTINUE[kind]
    positive = units[units >= 1]
    return float(np.sum(1.0 + (positive - 1.0) * cont))


def build_demand(
    catalog: Catalog,
    plan: ScenarioPlan,
    tl: Timelines,
    base_seed: int,
    scale: float,
    end_date: date,
) -> Demand:
    profile = catalog.profile
    n_days = plan.n_days
    dates = [plan.start + timedelta(days=i) for i in range(n_days)]
    lam, ev, pm = build_lambda(catalog, plan, tl, dates)
    q = np.array([p.q for p in catalog.products])
    size = np.array([p.nb_size for p in catalog.products])
    kind = "medical" if profile.is_medical else "fmcg"
    # Demand runs a little above the target because stock-outs turn some customers away.
    target = profile.target_lines_per_day * scale * 1.05
    factor = 1.0
    for _ in range(3):
        sample = _draw(lam * factor, q, size, stream(base_seed, profile.index, "calibrate"))
        per_day = _lines_of(sample, kind) / n_days
        factor *= target / max(per_day, 1e-6)
    demand = _draw(lam * factor, q, size, stream(base_seed, profile.index, "demand"))
    return Demand(
        true_demand=demand,
        lam=(lam * factor).astype(np.float32),
        event_mult=ev.astype(np.float32),
        promo_mult=pm.astype(np.float32),
        scale_factor=float(factor),
        dates=dates,
    )
