"""Planted scenarios S01 to S21 (`seed-data-spec.md` section 10).

`plan_scenarios` picks products deterministically from the catalogue and returns hooks the
simulation applies: blackouts (a supply gap), bulk receipts, discontinued items, launches, step
changes and so on. `scenarios.yaml` is written from the plan, with the expected engine behaviour.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import yaml

from seed.model import Catalog, ProductSpec
from seed.profiles import SCENARIOS_PATH, Profile, history_start
from seed.rng import stream
from seed.traits import MED_SPURIOUS, NO_EFFECT_PAIRS


@dataclass
class BulkOrder:
    """An extra purchase that arrives on a chosen day (bulk deal, short dated stock)."""

    product: int
    arrive_idx: int
    scenario: str
    cover_days: float | None = None  # quantity as days of expected demand
    remaining_days: int | None = None  # shelf life left at receipt, for tracked products
    sell_through: float | None = None  # quantity as a multiple of demand until expiry
    flags: set[str] = field(default_factory=set)  # no_writeoff, no_return
    note: str = ""


@dataclass
class ScenarioPlan:
    profile: Profile
    n_days: int
    start: date
    launch_idx: dict[int, int] = field(default_factory=dict)
    discontinue_idx: dict[int, int] = field(default_factory=dict)
    step_changes: list[tuple[int, int, float]] = field(default_factory=list)
    blackouts: dict[int, tuple[int, int]] = field(default_factory=dict)
    force_recorded: dict[int, bool] = field(default_factory=dict)
    stale_count: set[int] = field(default_factory=set)
    bulk_orders: list[BulkOrder] = field(default_factory=list)
    cost_events: list[tuple[int, int, float]] = field(default_factory=list)  # product, day, pct
    mrp_events: list[tuple[int, int, float]] = field(default_factory=list)
    cash_vendor_products: list[int] = field(default_factory=list)  # with a term, no lead time
    no_cost_products: list[int] = field(default_factory=list)  # bought over the counter
    unbatched: list[int] = field(default_factory=list)
    pack_excess: dict[int, tuple[int, int]] = field(default_factory=dict)
    overdue_supplier: int | None = None
    budget_factor: float = 1.05
    no_effect_pairs: tuple[tuple[str, str], ...] = ()
    spurious: tuple[str, str, float] | None = None
    scenarios: dict[str, dict[str, Any]] = field(default_factory=dict)

    def day(self, d: date) -> int:
        return (d - self.start).days


def _rate_rank(catalog: Catalog) -> list[ProductSpec]:
    return sorted(catalog.products, key=lambda p: -p.base_rate * p.mrp)


class _Picker:
    def __init__(self, products: list[ProductSpec], rng: np.random.Generator) -> None:
        self.products = products
        self.rng = rng
        self.used: set[int] = set()

    def pick(self, candidates: list[ProductSpec], k: int) -> list[ProductSpec]:
        pool = [p for p in candidates if p.index not in self.used]
        if len(pool) < k:
            raise RuntimeError(f"Not enough candidates for a scenario ({len(pool)} < {k})")
        order = self.rng.permutation(len(pool))[:k]
        chosen = [pool[int(i)] for i in order]
        self.used.update(p.index for p in chosen)
        return chosen


def _skus(items: list[ProductSpec]) -> list[str]:
    return [p.sku for p in items]


def plan_scenarios(catalog: Catalog, end_date: date, base_seed: int) -> ScenarioPlan:
    profile = catalog.profile
    start = history_start(end_date)
    n_days = (end_date - start).days + 1
    plan = ScenarioPlan(profile, n_days, start)
    rng = stream(base_seed, profile.index, "scenario")
    picker = _Picker(catalog.products, rng)
    ranked = _rate_rank(catalog)
    top_a = ranked[: max(10, len(ranked) // 6)]
    prods = catalog.products
    medical = profile.is_medical
    last = n_days - 1
    sc = plan.scenarios

    order_by_rate = sorted(prods, key=lambda p: p.base_rate)
    rank = {p.index: i / max(1, len(prods) - 1) for i, p in enumerate(order_by_rate)}

    def mid(lo: float, hi: float) -> list[ProductSpec]:
        """Products whose sales rate sits between two percentiles of this tenant."""
        return [p for p in prods if lo <= rank[p.index] <= hi]

    # S01 / S02: festival effects, with the negative cases.
    if not medical:
        sc["S01"] = {
            "summary": "Diwali 2025 category uplift in dry fruits, sweets and puja items",
            "event": "diwali-2025",
            "categories": ["dry-fruits", "chocolates-sweets", "festival-puja"],
            "products": _skus(
                [
                    p
                    for p in prods
                    if p.category in {"dry-fruits", "chocolates-sweets", "festival-puja"}
                ]
            ),
            "expect": "Learned effect for Diwali, applied with one occurrence, labelled learned",
        }
        plan.no_effect_pairs = NO_EFFECT_PAIRS[profile.key]
        sc["S02"] = {
            "summary": "Categories with no real effect for an event (negative case)",
            "pairs": [{"event": e, "category": c} for e, c in plan.no_effect_pairs],
            "products": _skus(
                [p for p in prods if p.category in {c for _, c in plan.no_effect_pairs}]
            ),
            "expect": "Effect computed but not applied, shown as not enough evidence",
        }
    else:
        event, category, mult = MED_SPURIOUS[profile.key]
        plan.spurious = (event, category, mult)
        sc["S02"] = {
            "summary": "Medical festival with a single occurrence and a chance uplift (negative case)",
            "event": f"{event}-2025",
            "category": category,
            "uplift": mult,
            "products": _skus([p for p in prods if p.category == category]),
            "expect": "Single occurrence is below the medical gate, so no festival effect is applied",
        }

    # S05 first: non-moving products need steady sellers that then stop.
    steady = [p for p in mid(0.35, 0.8) if not p.is_batch_tracked or medical]
    nonmoving = picker.pick(steady, 3)
    for p in nonmoving:
        plan.discontinue_idx[p.index] = last - int(rng.integers(85, 111))
    sc["S05"] = {
        "summary": "Three discontinued variants with stock still on the shelf",
        "products": _skus(nonmoving),
        "stops_on": [str(start + timedelta(days=plan.discontinue_idx[p.index])) for p in nonmoving],
        "expect": "Status non_moving",
    }

    # S06: out of stock for months, so they look dead.
    healthy = [p for p in mid(0.6, 0.9) if p.q >= 0.75]
    unverified = picker.pick(healthy, 2)
    for p in unverified:
        plan.blackouts[p.index] = (last - int(rng.integers(118, 130)), last + 40)
        plan.force_recorded[p.index] = False
    sc["S06"] = {
        "summary": "Two products out of stock for months, no sales and no availability",
        "products": _skus(unverified),
        "expect": "Status unverified, not non_moving",
    }

    # S03: recorded and unrecorded stockouts.
    candidates = [p for p in mid(0.45, 0.9) if p.q >= 0.75]
    recorded = picker.pick(candidates, 5)
    unrecorded = picker.pick(candidates, 5)
    starts_rec = [110, 190, 250, 330, last - 70]
    starts_unrec = [140, 220, 290, 380, last - 62]
    for group, starts, flag in ((recorded, starts_rec, True), (unrecorded, starts_unrec, False)):
        for p, s in zip(group, starts, strict=True):
            resume = last - 10 if s > last - 80 else s + int(rng.integers(18, 33))
            plan.blackouts[p.index] = (s, min(resume, last - 3))
            plan.force_recorded[p.index] = flag
    sc["S03"] = {
        "summary": "Five products with recorded stockouts and five with unrecorded ones",
        "recorded": _skus(recorded),
        "unrecorded": _skus(unrecorded),
        "expect": "Censored days excluded, CENSORED_HISTORY on the recent ones, recorded intervals respected",
    }

    # S04: slow movers with big overstock (fmcg_b, med_b).
    if profile.key in {"fmcg_b", "med_b"}:
        by_rate = sorted(
            (p for p in prods if p.index not in picker.used), key=lambda p: p.base_rate
        )
        slow = picker.pick(by_rate[:24], 6)
        for p in slow:
            plan.bulk_orders.append(
                BulkOrder(
                    p.index,
                    last - int(rng.integers(50, 120)),
                    "S04",
                    cover_days=float(rng.uniform(150, 300)),
                    note="bulk deal",
                )
            )
        sc["S04"] = {
            "summary": "Six slow movers with a large bulk purchase",
            "products": _skus(slow),
            "expect": "Appear under Reduce exposure, no purchase suggested",
        }

    # S07: an open order overdue by six or more days.
    pool = [s for s in catalog.suppliers if s.planted is None]
    plan.overdue_supplier = pool[int(rng.integers(0, len(pool)))].index
    sc["S07"] = {
        "summary": "An open purchase order overdue by six or more days",
        "supplier": catalog.suppliers[plan.overdue_supplier].code,
        "expect": "PO_OVERDUE, incoming excluded from confident stock, watch tag",
    }

    # S08 / S09: budgets.
    plan.budget_factor = 0.70 if profile.key == "fmcg_a" else 1.05
    sc["S08" if profile.key == "fmcg_a" else "S09"] = {
        "summary": "Weekly budget at 70 percent of need"
        if profile.key == "fmcg_a"
        else "Weekly budget at 105 percent of need",
        "budget_factor": plan.budget_factor,
        "expect": "Shortfall and unfunded lines with critical warnings"
        if profile.key == "fmcg_a"
        else "No shortfall",
    }

    # S10: missing data.
    cv_candidates = [
        p for p in mid(0.3, 0.75) if (medical or not p.is_batch_tracked) and p.q >= 0.75
    ]
    cash = picker.pick(cv_candidates, 3)
    plan.cash_vendor_products = [cash[0].index, cash[1].index]
    plan.no_cost_products = [cash[2].index]
    unb_pool = [p for p in mid(0.3, 0.75) if p.is_batch_tracked and p.q >= 0.75]
    unbatched = picker.pick(unb_pool, 1)
    plan.unbatched = [unbatched[0].index]
    sc["S10"] = {
        "summary": "Two products without a lead time, one without a cost, one batch tracked product with stock but no batch",
        "missing_lead_time": _skus(cash[:2]),
        "missing_cost": _skus(cash[2:]),
        "missing_expiry": _skus(unbatched),
        "expect": "MISSING_LEAD_TIME, MISSING_COST and MISSING_EXPIRY warnings, lower confidence, no order for the missing cost item",
    }

    # S11: supplier price rise in January 2026.
    price_day = plan.day(date(2026, 1, 12))
    if not medical:
        oils = [p for p in prods if p.category == "edible-oils-ghee"]
        for p in oils:
            plan.cost_events.append((p.index, price_day, 9.0))
            plan.mrp_events.append((p.index, price_day + 28, 5.0))
        affected = oils
    else:
        chronic = [p for p in prods if p.chronic and p.index not in picker.used]
        by_maker: dict[str, list[ProductSpec]] = {}
        for p in chronic:
            by_maker.setdefault(p.manufacturer or "", []).append(p)
        group = max(by_maker.values(), key=len)[:3]
        for p in group:
            plan.cost_events.append((p.index, price_day, 9.0))
        affected = group
    sc["S11"] = {
        "summary": "Supplier price up 9 percent in January 2026",
        "effective": "2026-01-12",
        "products": _skus(affected),
        "expect": "No PRICE_ANOMALY (under 30 percent), spend uses the new price",
    }

    # S12 / S13 / S14: expiry exposure.
    if profile.key == "med_a":
        pool = [
            p
            for p in prods
            if p.is_batch_tracked and rank[p.index] >= 0.3 and p.index not in picker.used
        ]
        near = picker.pick(pool, 4)
        for p in near:
            r = int(rng.integers(110, 190))
            arrive = last + int(rng.integers(18, 80)) - r
            plan.bulk_orders.append(
                BulkOrder(
                    p.index,
                    arrive,
                    "S12",
                    remaining_days=r,
                    sell_through=float(rng.uniform(1.8, 2.5)),
                    flags={"no_return"},
                )
            )
        expired = picker.pick(pool, 1)[0]
        r = 130
        plan.bulk_orders.append(
            BulkOrder(
                expired.index,
                last - 6 - r,
                "S12",
                remaining_days=r,
                sell_through=2.4,
                flags={"no_writeoff", "no_return"},
            )
        )
        sc["S12"] = {
            "summary": "Four batches within 90 days of expiry and one already expired with stock",
            "near_expiry": _skus(near),
            "expired": [expired.sku],
            "expect": "Expiry list with batch, quantity and value, WRITE_OFF_NEEDED for the expired batch",
        }
    if profile.key == "med_b":
        accepting = {s.index for s in catalog.suppliers if s.accepts_expiry_returns}
        pool_all = [
            p
            for p in prods
            if p.is_batch_tracked and rank[p.index] >= 0.25 and p.index not in picker.used
        ]
        returnable = picker.pick([p for p in pool_all if p.supplier in accepting], 3)
        others = picker.pick([p for p in pool_all if p.supplier not in accepting], 11)
        for p in returnable + others:
            r = int(rng.integers(110, 190))
            arrive = last + int(rng.integers(12, 85)) - r
            flags = {"no_return"}
            plan.bulk_orders.append(
                BulkOrder(
                    p.index,
                    arrive,
                    "S13",
                    remaining_days=r,
                    sell_through=float(rng.uniform(1.8, 2.8)),
                    flags=flags,
                )
            )
        sc["S13"] = {
            "summary": "Fourteen near-expiry batches with large exposure, three from suppliers that accept returns",
            "returnable": _skus(returnable),
            "not_returnable": _skus(others),
            "expect": "High exposure total and operational options that respect each return policy",
        }
    if medical:
        # Short dated bulk deals earlier in the history that mostly expired, so write offs exist.
        deals = 12 if profile.key == "med_b" else 4
        pool = [
            p
            for p in prods
            if p.is_batch_tracked and rank[p.index] >= 0.3 and p.index not in picker.used
        ]
        history = picker.pick(pool, deals)
        for p in history:
            r = int(rng.integers(90, 151))
            arrive = int(rng.integers(60, last - 170))
            plan.bulk_orders.append(
                BulkOrder(
                    p.index,
                    arrive,
                    "S13h",
                    remaining_days=r,
                    sell_through=float(rng.uniform(2.0, 3.0)),
                    note="short dated deal",
                )
            )
        target = sc["S12"] if profile.key == "med_a" else sc["S13"]
        target["history_deals"] = _skus(history)
    if not medical:
        dated = [
            p
            for p in prods
            if p.category in {"namkeen-snacks", "dairy-eggs"} and p.index not in picker.used
        ]
        shortlife = picker.pick(dated, 3)
        for p in shortlife:
            r = (
                int(rng.integers(55, 120))
                if p.category == "namkeen-snacks"
                else int(rng.integers(40, 60))
            )
            arrive = last + int(rng.integers(6, 36)) - r
            plan.bulk_orders.append(
                BulkOrder(
                    p.index,
                    arrive,
                    "S14",
                    remaining_days=r,
                    sell_through=float(rng.uniform(1.6, 2.4)),
                    flags={"no_return"},
                )
            )
        sc["S14"] = {
            "summary": "Three dated products with expiry exposure",
            "products": _skus(shortlife),
            "expect": "Expiry cap reduces the suggested quantity (EXPIRY_CAP)",
        }

    # S15: new launches five weeks before the end.
    new_pool = [p for p in mid(0.4, 0.85) if p.q >= 0.75]
    new_items = picker.pick(new_pool, 2)
    for p in new_items:
        plan.launch_idx[p.index] = last - 34
        p.launched_on = start + timedelta(days=last - 34)
    sc["S15"] = {
        "summary": "Two new products launched five weeks before the end",
        "products": _skus(new_items),
        "launched_on": str(start + timedelta(days=last - 34)),
        "expect": "Class new, low confidence, category prior",
    }

    # S16: pack and minimum order sizes that force a big excess.
    slow_pool = sorted(
        (p for p in prods if p.index not in picker.used and not p.is_batch_tracked),
        key=lambda p: p.base_rate,
    )[:14]
    forced = picker.pick(slow_pool, 4)
    for p in forced:
        big = 100 if medical else 48
        plan.pack_excess[p.index] = (big, 2 * big)
    sc["S16"] = {
        "summary": "Four products where pack size and minimum order force a large excess",
        "products": _skus(forced),
        "expect": "PACK_ROUNDING and MOQ_APPLIED reasons",
    }

    # S17: A class products without a recent count.
    stale = picker.pick([p for p in top_a if p.q >= 0.75], 3)
    plan.stale_count = {p.index for p in stale}
    sc["S17"] = {
        "summary": "Three A class products without a stock count for more than 45 days",
        "products": _skus(stale),
        "expect": "STALE_STOCK_COUNT",
    }

    # S18 / S19: medical patterns, recorded for the tests.
    if medical:
        chronic_products = [p for p in prods if p.chronic]
        sc["S18"] = {
            "summary": "Chronic medicines with a month start refill pattern",
            "products": _skus(chronic_products),
            "expect": "Weekday and month day patterns, forecast confidence high",
        }
        monsoon_categories = [
            "analgesics-antipyretics",
            "gastro-antacids",
            "respiratory-cough-cold",
            "dermatology",
            "antibiotics",
        ]
        sc["S19"] = {
            "summary": "Monsoon illness lift categories",
            "categories": monsoon_categories,
            "expect": "Season effect learned and applied, labelled seasonal",
        }

    # S20: a step change in demand.
    stepper = picker.pick([p for p in mid(0.8, 0.97) if p.q >= 0.75], 4)
    plan.step_changes.append((stepper[0].index, last - 190, 1.5))
    for p in stepper[1:]:
        plan.step_changes.append(
            (p.index, int(rng.integers(150, last - 120)), float(rng.choice([0.75, 1.3, 1.35])))
        )
    sc["S20"] = {
        "summary": "One product with a mid-year step change in demand of 50 percent",
        "products": _skus(stepper[:1]),
        "starts_on": str(start + timedelta(days=last - 190)),
        "other_step_changes": _skus(stepper[1:]),
        "expect": "Forecast bias after the step, then adaptation, visible in the accuracy insight",
    }

    # S21: the upcoming Navratri and Diwali windows.
    sc["S21"] = {
        "summary": "Upcoming Navratri and Dussehra and Diwali 2026 around the first plan",
        "as_of": str(end_date + timedelta(days=1)),
        "events": ["navratri_dussehra-2026", "diwali-2026"],
        "expect": "Festival section shows both, with the Diwali pre window reaching into the horizon",
    }
    return plan


def write_scenarios_yaml(plans: list[ScenarioPlan], end_date: date, path: Any = None) -> None:
    out: dict[str, Any] = {
        "note": "Planted scenarios. SKUs are picked deterministically from the catalogues. Synthetic data.",
        "end_date": str(end_date),
        "tenants": {},
    }
    for plan in plans:
        out["tenants"][plan.profile.key] = dict(sorted(plan.scenarios.items()))
    target = path or SCENARIOS_PATH
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(out, handle, sort_keys=False, allow_unicode=True, width=100)
