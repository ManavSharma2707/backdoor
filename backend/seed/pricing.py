"""Price, promotion and supplier cost timelines for one tenant.

The result is a set of day by day arrays (products x days) so the demand model and the simulation
read the same prices, plus the promotion list and change events the loader turns into rows.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from seed.model import Catalog
from seed.profiles import history_start
from seed.rng import stream
from seed.scenarios import ScenarioPlan

PROMO_NAMES = (
    "Weekend saver",
    "Monthly bonanza",
    "Combo offer",
    "Festival offer",
    "Season sale",
    "Customer favourite",
)


@dataclass
class Promotion:
    index: int
    name: str
    kind: str
    product: int | None
    category: str | None
    discount_pct: float
    start_idx: int
    end_idx: int
    uplift: float = 1.0


@dataclass
class Timelines:
    mrp: np.ndarray  # paise, int32 [n, T]
    sell: np.ndarray  # paise, int32 [n, T]
    cost: np.ndarray  # 1/10000 rupee, int64 [n, T]
    promo: np.ndarray  # promotion index or -1, int16 [n, T]
    promotions: list[Promotion] = field(default_factory=list)
    price_changes: list[tuple[int, int, float]] = field(default_factory=list)


def _rupee_round(paise_value: float) -> int:
    return round(paise_value / 100.0) * 100


def build_timelines(
    catalog: Catalog, plan: ScenarioPlan, base_seed: int, end_date: date
) -> Timelines:
    profile = catalog.profile
    products = catalog.products
    n, t_days = len(products), plan.n_days
    rng = stream(base_seed, profile.index, "price")
    mrp = np.empty((n, t_days), dtype=np.int32)
    sell = np.empty((n, t_days), dtype=np.int32)
    cost = np.empty((n, t_days), dtype=np.int64)
    for p in products:
        mrp[p.index, :] = p.mrp
        sell[p.index, :] = p.selling_price
        cost[p.index, :] = p.purchase_price
    tl = Timelines(mrp, sell, cost, np.full((n, t_days), -1, dtype=np.int16))

    protected = set(plan.launch_idx) | set(plan.discontinue_idx)
    n_changes = round(0.10 * n * t_days / 365.0)
    eligible = [p.index for p in products if p.index not in protected]
    chosen = rng.choice(eligible, size=min(n_changes, len(eligible)), replace=False)
    for pi in sorted(int(c) for c in chosen):
        day = int(rng.integers(30, t_days - 40))
        pct = float(rng.uniform(2.0, 6.0))
        _raise_mrp(tl, pi, day, pct)
        lag = int(rng.integers(3, 11))
        tl.cost[pi, day + lag :] = np.round(tl.cost[pi, day + lag :] * (1 + pct / 100.0)).astype(
            np.int64
        )
        tl.price_changes.append((pi, day, pct))

    for pi, day, pct in plan.cost_events:
        tl.cost[pi, day:] = np.round(tl.cost[pi, day:] * (1 + pct / 100.0)).astype(np.int64)
    for pi, day, pct in plan.mrp_events:
        if day < t_days:
            _raise_mrp(tl, pi, day, pct)
            tl.price_changes.append((pi, day, pct))

    _add_promotions(tl, catalog, plan, rng, end_date)
    return tl


def _raise_mrp(tl: Timelines, pi: int, day: int, pct: float) -> None:
    old_mrp = int(tl.mrp[pi, day])
    old_sell = int(tl.sell[pi, day])
    new_mrp = max(old_mrp + 100, _rupee_round(old_mrp * (1 + pct / 100.0)))
    new_sell = min(new_mrp, max(old_sell + 100, _rupee_round(old_sell * (1 + pct / 100.0))))
    if old_sell == old_mrp:
        new_sell = new_mrp
    tl.mrp[pi, day:] = new_mrp
    tl.sell[pi, day:] = new_sell


def _add_promotions(
    tl: Timelines, catalog: Catalog, plan: ScenarioPlan, rng: np.random.Generator, end_date: date
) -> None:
    profile = catalog.profile
    products = catalog.products
    t_days = plan.n_days
    if profile.key == "fmcg_b":
        count = 14
    elif profile.key == "fmcg_a":
        count = 10
    else:
        count = 10
    busy: dict[int, list[tuple[int, int]]] = {}
    by_category: dict[str, list[int]] = {}
    for p in products:
        by_category.setdefault(p.category, []).append(p.index)
    kinds = ("discount", "discount", "festival_offer", "bundle", "bogo")
    attempts = 0
    while len(tl.promotions) < count and attempts < 400:
        attempts += 1
        length = int(rng.integers(5, 15))
        start = int(rng.integers(20, t_days - length - 14))
        end = start + length - 1
        if rng.random() < 0.7:
            pi = int(rng.integers(0, len(products)))
            members = [pi]
            category = None
            product: int | None = pi
        else:
            category = str(rng.choice(sorted(by_category)))
            members = by_category[category]
            product = None
        if any(m in plan.launch_idx or m in plan.discontinue_idx for m in members):
            continue
        if any(s <= end and start <= e for m in members for s, e in busy.get(m, [])):
            continue
        discount = float(rng.integers(5, 26))
        kind = str(rng.choice(kinds))
        promo = Promotion(
            index=len(tl.promotions),
            name=str(rng.choice(PROMO_NAMES)),
            kind=kind,
            product=product,
            category=category,
            discount_pct=discount,
            start_idx=start,
            end_idx=end,
            uplift=float(rng.uniform(1.3, 2.2)),
        )
        tl.promotions.append(promo)
        for m in members:
            busy.setdefault(m, []).append((start, end))
            seg = slice(start, end + 1)
            base_sell = tl.sell[m, seg].astype(np.float64)
            floor = np.ceil(tl.cost[m, seg] / 100.0 * 1.03 / 100.0) * 100.0
            promo_price = np.floor(base_sell * (1 - discount / 100.0) / 100.0) * 100.0
            tl.sell[m, seg] = np.maximum(promo_price, np.minimum(floor, base_sell)).astype(np.int32)
            tl.promo[m, seg] = promo.index


def history_dates(end_date: date, n_days: int) -> list[date]:
    start = history_start(end_date)
    return [start + timedelta(days=i) for i in range(n_days)]
