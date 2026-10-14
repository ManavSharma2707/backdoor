"""Day by day simulation of one shop: demand meets stock, bills, returns, orders and receipts.

The output is a set of row tuples in the column order of `seed.schema.COLUMNS`, written the way the
services would write them (same movement types and sign rules, same document number formats), plus
the arrays the validators and the realism report read. Quantities are whole units and money is
kept in integer paise (unit costs in ten thousandths of a rupee) until the rows are built.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from seed.demand import LINE_QTY_CONTINUE, Demand
from seed.model import (
    K_ADJ,
    K_BATCH,
    K_CLINE,
    K_COUNT,
    K_PO,
    K_POLINE,
    K_PROMO,
    K_RECEIPT,
    K_RETURN,
    K_RLINE,
    K_SALE,
    K_STOCKOUT,
    Catalog,
    cost4,
    ist_midnight_utc,
    make_uuid,
    money,
    tenant_uuid,
)
from seed.pricing import Timelines
from seed.rng import stream
from seed.scenarios import BulkOrder, ScenarioPlan
from seed.schema import COLUMNS

FMCG_HOURS = {
    8: 0.03,
    9: 0.09,
    10: 0.11,
    11: 0.08,
    12: 0.06,
    13: 0.04,
    14: 0.025,
    15: 0.025,
    16: 0.04,
    17: 0.10,
    18: 0.12,
    19: 0.12,
    20: 0.09,
    21: 0.04,
}
MED_HOURS = {
    9: 0.04,
    10: 0.11,
    11: 0.12,
    12: 0.11,
    13: 0.07,
    14: 0.04,
    15: 0.04,
    16: 0.05,
    17: 0.07,
    18: 0.11,
    19: 0.12,
    20: 0.09,
    21: 0.03,
}
PAYMENT = {
    "fmcg": (("cash", "upi", "card", "credit"), (0.45, 0.45, 0.07, 0.03)),
    "medical": (("cash", "upi", "card", "credit"), (0.35, 0.55, 0.08, 0.02)),
}
TAX_PCT = {"GST0": 0, "GST5": 5, "GST18": 18, "GST40": 40}
RETURN_REASONS = ("Customer changed mind", "Wrong item picked", "Pack damaged", "Past best before")
OFFSET_WEIGHTS = (0.4, 0.3, 0.2, 0.1)
# A top-up to reach the supplier minimum never takes an item past this many days of cover.
TOP_UP_COVER_DAYS = 40
IDX = {table: {c: i for i, c in enumerate(cols)} for table, cols in COLUMNS.items()}


class Batch:
    __slots__ = ("cost4", "expiry", "idx", "product", "qty", "row")

    def __init__(self, idx: int, product: int, expiry: int, qty: int, cost: int, row: int) -> None:
        self.idx = idx
        self.product = product
        self.expiry = expiry  # date ordinal
        self.qty = qty
        self.cost4 = cost
        self.row = row


class POLine:
    __slots__ = ("cost4", "id", "pack", "product", "qty", "received", "row")

    def __init__(
        self, line_id: int, product: int, qty: int, cost: int, pack: int, row: int
    ) -> None:
        self.id = line_id
        self.product = product
        self.qty = qty
        self.cost4 = cost
        self.pack = pack
        self.received = 0
        self.row = row


class PO:
    __slots__ = (
        "arrival_idx",
        "backorder_idx",
        "bulk",
        "expected_idx",
        "id",
        "lines",
        "number",
        "order_idx",
        "row",
        "status",
        "supplier",
    )

    def __init__(self, po_id: int, supplier: int, number: str, order_idx: int, row: int) -> None:
        self.id = po_id
        self.supplier = supplier
        self.number = number
        self.order_idx = order_idx
        self.row = row
        self.lines: list[POLine] = []
        self.expected_idx = 0
        self.arrival_idx = 0
        self.backorder_idx = -1
        self.status = "sent"
        self.bulk: BulkOrder | None = None


@dataclass
class TenantData:
    rows: dict[str, list[Any]]
    true_demand: np.ndarray
    event_mult: np.ndarray
    promo_mult: np.ndarray
    closing: np.ndarray
    sold: np.ndarray
    lost: np.ndarray
    out_all_day: np.ndarray
    final_balances: dict[tuple[int, int | None], tuple[int, int, datetime | None]]
    batch_info: list[dict[str, Any]]
    weekly_cogs: list[float]
    stats: dict[str, float] = field(default_factory=dict)
    movement_count: int = 0


class Simulation:
    def __init__(
        self,
        catalog: Catalog,
        plan: ScenarioPlan,
        tl: Timelines,
        demand: Demand,
        base_seed: int,
        end_date: date,
        scale: float,
    ) -> None:
        self.cat = catalog
        self.profile = catalog.profile
        self.plan = plan
        self.tl = tl
        self.dem = demand
        self.base_seed = base_seed
        self.end_date = end_date
        self.scale = scale
        self.kind = "medical" if self.profile.is_medical else "fmcg"
        self.n = len(catalog.products)
        self.T = plan.n_days
        self.dates = demand.dates
        self.ti = self.profile.index
        self.tenant = tenant_uuid(self.profile)
        self.opening_date = plan.start - timedelta(days=1)
        self.mid = [ist_midnight_utc(d) for d in self.dates]
        self.mid_open = ist_midnight_utc(self.opening_date)
        self.counter: dict[int, int] = defaultdict(int)
        self.rows: dict[str, list[Any]] = {name: [] for name in COLUMNS}
        self.p_uuid = [make_uuid(self.ti, 4, p.index + 1) for p in catalog.products]
        self.sup_uuid = [make_uuid(self.ti, 5, s.index + 1) for s in catalog.suppliers]
        self.promo_uuid = [make_uuid(self.ti, K_PROMO, i + 1) for i in range(len(tl.promotions))]
        self.cost_str: dict[int, str] = {}
        self.mv_seq = self.ti * 10_000_000
        self.line_seq = self.ti * 10_000_000
        self.rline_seq = self.ti * 10_000_000
        self._setup_products()
        self._setup_suppliers()
        self.stock = [0] * self.n
        self.batches: list[list[Batch]] = [[] for _ in range(self.n)]
        self.avg4 = [0] * self.n
        self.total = [0] * self.n
        self.incoming = [0] * self.n
        self.all_batches: list[Batch] = []
        self.batch_numbers: list[set[str]] = [set() for _ in range(self.n)]
        self.arrivals: dict[int, list[tuple[str, PO]]] = defaultdict(list)
        self.writeoffs: dict[int, list[Batch]] = defaultdict(list)
        self.sup_returns: dict[int, list[Batch]] = defaultdict(list)
        self.batch_flags: dict[int, set[str]] = {}
        self.pending_returns: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
        self.sold = np.zeros((self.n, self.T), dtype=np.int32)
        self.lost = np.zeros((self.n, self.T), dtype=np.int32)
        self.closing = np.zeros((self.n, self.T), dtype=np.int32)
        self.out_all_day = np.zeros((self.n, self.T), dtype=bool)
        self.recv_today = [False] * self.n
        self.run_start = [-1] * self.n
        self.last_move: dict[tuple[int, int | None], datetime] = {}
        self.seq_bill: dict[str, int] = defaultdict(int)
        self.seq_return: dict[str, int] = defaultdict(int)
        self.seq_po: dict[str, int] = defaultdict(int)
        self.seq_receipt: dict[str, int] = defaultdict(int)
        self.weekly_cogs: list[float] = []
        self.overdue_done = False
        self.stats: dict[str, float] = defaultdict(float)
        self.bulk_by_order: dict[int, list[BulkOrder]] = defaultdict(list)
        self.count_days = self._count_days()
        self.rev_rank = self._revenue_rank()
        self.rop_extra = {"fmcg_a": 2.5, "med_a": 4.6}.get(self.profile.key, 3.8)
        self.target_extra = 8.0 if self.profile.key == "fmcg_a" else 9.0
        self.p_dmg = float(self.R("adjust", 0).uniform(0.001, 0.003))

    # ------------------------------------------------------------------ setup
    def R(self, purpose: str, t: int) -> np.random.Generator:
        return stream(self.base_seed, self.ti, purpose, t + 1)

    def next_id(self, kind: int) -> int:
        self.counter[kind] += 1
        return self.counter[kind]

    def _setup_products(self) -> None:
        plan = self.plan
        cash = self.cat.suppliers[-1].index
        for pi in plan.cash_vendor_products:
            p = self.cat.products[pi]
            p.supplier = cash
            p.term_lead_time_days = None
        for pi in plan.no_cost_products:
            p = self.cat.products[pi]
            p.supplier = cash
            p.has_term = False
        for pi in plan.unbatched:
            self.cat.products[pi].unbatched = True
        for pi, (pack, moq) in plan.pack_excess.items():
            self.cat.products[pi].pack_size = pack
            self.cat.products[pi].moq_units = moq
        self.tracked = [p.is_batch_tracked and not p.unbatched for p in self.cat.products]
        self.tax_pct = [TAX_PCT[p.tax] for p in self.cat.products]

    def _setup_suppliers(self) -> None:
        if self.scale >= 1.0:
            return
        for s in self.cat.suppliers:
            if s.min_order_value:
                s.min_order_value = max(100_00, int(s.min_order_value * self.scale) // 100 * 100)

    def _revenue_rank(self) -> list[int]:
        order = sorted(
            range(self.n), key=lambda p: -self.cat.products[p].base_rate * self.cat.products[p].mrp
        )
        return order

    def _count_days(self) -> list[int]:
        rng = self.R("counts", 0)
        days: list[int] = []
        t = self.T - 1 - 12
        while t > 25:
            days.append(t + int(rng.integers(-3, 4)))
            t -= 31
        return sorted(days)

    # ------------------------------------------------------------------ helpers
    def at(self, t: int, seconds: float) -> datetime:
        return self.mid[t] + timedelta(seconds=float(seconds))

    def c4(self, value: int) -> str:
        s = self.cost_str.get(value)
        if s is None:
            s = self.cost_str[value] = cost4(value)
        return s

    def lead(self, p: int) -> int:
        prod = self.cat.products[p]
        if prod.term_lead_time_days is not None:
            return prod.term_lead_time_days
        sup = self.cat.suppliers[prod.supplier]
        return sup.default_lead_time_days if sup.default_lead_time_days is not None else 1

    def move(
        self,
        p: int,
        batch: Batch | None,
        mtype: str,
        qty: int,
        unit_cost: int,
        when: datetime,
        d: date,
        src_type: str,
        src_id: str,
        reason: str | None = None,
        note: str | None = None,
        reverses: int | None = None,
    ) -> int:
        self.mv_seq += 1
        b_uuid = make_uuid(self.ti, K_BATCH, batch.idx + 1) if batch is not None else None
        self.rows["inventory_movements"].append(
            (
                self.mv_seq,
                self.tenant,
                self.p_uuid[p],
                b_uuid,
                mtype,
                qty,
                self.c4(unit_cost),
                when,
                d,
                src_type,
                src_id,
                reason,
                note,
                reverses,
                when,
            )
        )
        self.last_move[(p, batch.idx if batch is not None else None)] = when
        return self.mv_seq

    def add_stock(self, p: int, batch: Batch | None, qty: int, unit_cost: int) -> None:
        """Bring `qty` into stock; untracked stock moves its weighted average cost."""
        if batch is not None:
            batch.qty += qty
        else:
            before = self.stock[p]
            if before > 0:
                self.avg4[p] = (before * self.avg4[p] + qty * unit_cost + (before + qty) // 2) // (
                    before + qty
                )
            else:
                self.avg4[p] = unit_cost
            self.stock[p] = before + qty
        self.total[p] += qty

    def new_batch(
        self,
        p: int,
        qty: int,
        received: date,
        t: int,
        cost: int,
        remaining_days: int | None = None,
        remaining_frac: tuple[float, float] = (0.55, 0.90),
        flags: set[str] | None = None,
    ) -> Batch:
        prod = self.cat.products[p]
        rng = self.R("batch", (t + 1) * 1000 + p)
        shelf = prod.shelf_life_days or 365
        if remaining_days is None:
            remaining_days = max(25, int(shelf * float(rng.uniform(*remaining_frac))))
        expiry = received + timedelta(days=remaining_days)
        manufactured = expiry - timedelta(days=shelf)
        used = self.batch_numbers[p]
        for _ in range(50):
            no = f"{chr(65 + int(rng.integers(0, 26)))}{int(rng.integers(1, 10))}{chr(65 + int(rng.integers(0, 26)))}{int(rng.integers(10, 100))}"
            if no not in used:
                break
        else:
            no = f"X{len(used) + 1:04d}"
        used.add(no)
        idx = self.next_id(K_BATCH) - 1
        row = len(self.rows["product_batches"])
        mrp = self.mrp_at(p, max(0, min(t, self.T - 1)))
        self.rows["product_batches"].append(
            [
                make_uuid(self.ti, K_BATCH, idx + 1),
                self.tenant,
                self.p_uuid[p],
                no,
                expiry,
                manufactured,
                money(mrp),
                self.c4(cost),
                received,
                qty,
                "active",
                self.at(max(t, 0), 8 * 3600) if t >= 0 else self.mid_open,
            ]
        )
        batch = Batch(idx, p, expiry.toordinal(), 0, cost, row)
        self.all_batches.append(batch)
        lst = self.batches[p]
        lst.append(batch)
        lst.sort(key=lambda b: (b.expiry, b.idx))
        if flags:
            self.batch_flags[idx] = flags
        self._schedule_expiry(batch, t, remaining_days, flags or set())
        return batch

    def mrp_at(self, p: int, t: int) -> int:
        return int(self.tl.mrp[p, t])

    def _schedule_expiry(self, batch: Batch, t: int, remaining_days: int, flags: set[str]) -> None:
        rng = self.R("batch", 700_000 + batch.idx)
        expiry_idx = batch.expiry - self.plan.start.toordinal()
        if "no_writeoff" not in flags:
            due = expiry_idx + int(rng.integers(1, 11))
            if due < self.T:
                self.writeoffs[max(due, t + 1)].append(batch)
        sup = self.cat.suppliers[self.cat.products[batch.product].supplier]
        if "no_return" not in flags and sup.accepts_expiry_returns and rng.random() < 0.20:
            window = sup.expiry_return_window_days or 60
            lead = int(rng.integers(30, min(60, window) + 1))
            due = expiry_idx - lead
            if t < due < self.T:
                self.sup_returns[due].append(batch)

    # ------------------------------------------------------------------ opening
    def open_stock(self) -> None:
        rng = self.R("batch", 0)
        d0 = self.opening_date
        for p in self.cat.products:
            pi = p.index
            if pi in self.plan.launch_idx:
                continue
            avg = float(self.dem.lam[pi, :14].mean())
            qty = max(1, math.ceil(avg * float(rng.uniform(14, 35))))
            cost = int(p.purchase_price * float(rng.uniform(0.96, 1.0)))
            if self.tracked[pi]:
                parts = 3 if qty >= 6 else (2 if qty >= 2 else 1)
                shares = np.sort(rng.dirichlet(np.ones(parts)))[::-1]
                quantities = [max(1, round(qty * s)) for s in shares]
                shelf = p.shelf_life_days or 365
                fracs = sorted(float(rng.uniform(0.25, 0.85)) for _ in range(parts))
                for q_i, frac in zip(quantities, fracs, strict=True):
                    batch = self.new_batch(
                        pi, q_i, d0, -1, cost, remaining_days=max(25, int(shelf * frac))
                    )
                    self.add_stock(pi, batch, q_i, cost)
                    self.move(
                        pi,
                        batch,
                        "opening",
                        q_i,
                        cost,
                        self.mid_open + timedelta(hours=1),
                        d0,
                        "opening",
                        "opening",
                    )
            else:
                self.add_stock(pi, None, qty, cost)
                self.move(
                    pi,
                    None,
                    "opening",
                    qty,
                    cost,
                    self.mid_open + timedelta(hours=1),
                    d0,
                    "opening",
                    "opening",
                )

    # ------------------------------------------------------------------ purchasing
    def sellable(self, p: int, d_ord: int) -> int:
        if not self.tracked[p]:
            return self.stock[p]
        return sum(b.qty for b in self.batches[p] if b.qty > 0 and b.expiry > d_ord)

    def blocked(self, p: int, t: int) -> bool:
        window = self.plan.blackouts.get(p)
        return window is not None and window[0] <= t < window[1]

    def day_date(self, idx: int) -> date:
        return self.plan.start + timedelta(days=idx)

    def delivery_roll(self, supplier: int, day_idx: int) -> int:
        """The first day on or after `day_idx` that the supplier delivers."""
        weekdays = self.cat.suppliers[supplier].delivery_weekdays
        for k in range(8):
            if self.day_date(day_idx + k).isoweekday() in weekdays:
                return day_idx + k
        return day_idx

    def po_number(self, order_date: date) -> str:
        key = f"{order_date:%y%m}"
        self.seq_po[key] += 1
        return f"PO{key}-{self.seq_po[key]:04d}"

    def make_po(
        self,
        supplier: int,
        t: int,
        specs: list[tuple[int, int]],
        arrival_idx: int | None = None,
        bulk: BulkOrder | None = None,
        note: str | None = None,
        stuck: bool = False,
    ) -> PO:
        rng = self.R("delivery", t * 10 + supplier)
        sup = self.cat.suppliers[supplier]
        d = self.dates[t]
        po_id = self.next_id(K_PO)
        po = PO(po_id, supplier, self.po_number(d), t, len(self.rows["purchase_orders"]))
        po_uuid = make_uuid(self.ti, K_PO, po_id)
        lead = max(self.lead(p) for p, _ in specs)
        expected = t + lead
        if arrival_idx is None:
            expected = self.delivery_roll(supplier, expected)
            arrival = expected
            if rng.random() < sup.delay_prob:
                arrival += int(rng.integers(sup.delay_days_min, sup.delay_days_max + 1))
        else:
            expected = arrival = arrival_idx
        natural = (
            not self.overdue_done
            and bulk is None
            and supplier == self.plan.overdue_supplier
            and t >= self.T - 18
            and expected <= self.T - 6
        )
        if stuck or natural:
            arrival = self.T + 25
            expected = min(expected, self.T - 7) if stuck else expected
            self.overdue_done = True
            self.stats["overdue_po"] = po_id
        po.expected_idx = expected
        po.arrival_idx = arrival
        po.bulk = bulk
        subtotal = 0
        for p, qty in specs:
            prod = self.cat.products[p]
            cost = int(self.tl.cost[p, t])
            line_id = self.next_id(K_POLINE)
            line = POLine(
                line_id, p, qty, cost, prod.pack_size, len(self.rows["purchase_order_lines"])
            )
            po.lines.append(line)
            self.rows["purchase_order_lines"].append(
                [
                    make_uuid(self.ti, K_POLINE, line_id),
                    self.tenant,
                    po_uuid,
                    self.p_uuid[p],
                    qty,
                    self.c4(cost),
                    prod.pack_size,
                    0,
                    self.at(t, 10 * 3600),
                ]
            )
            subtotal += round(qty * cost / 100.0)
            self.incoming[p] += qty
        exp_date = self.day_date(expected)
        self.rows["purchase_orders"].append(
            [
                po_uuid,
                self.tenant,
                self.sup_uuid[supplier],
                po.number,
                "sent",
                d,
                exp_date,
                self.at(t, 10 * 3600 + 600),
                None,
                None,
                money(subtotal),
                "seed",
                note,
                self.at(t, 10 * 3600),
                self.at(t, 10 * 3600),
            ]
        )
        if arrival < self.T:
            self.arrivals[arrival].append(("arrive", po))
        return po

    def avg14(self, t: int) -> np.ndarray:
        """The owner's idea of daily demand: recent sales plus half the customers turned away,
        counting only days the product was on the shelf."""
        if t < 7:
            return self.dem.lam[:, :14].mean(axis=1)

        def recent(width: int) -> np.ndarray:
            lo = max(0, t - width)
            seen = self.sold[:, lo:t] + 0.5 * self.lost[:, lo:t]
            on_shelf = ~self.out_all_day[:, lo:t]
            days = np.maximum(on_shelf.sum(axis=1), 1)
            return (seen * on_shelf).sum(axis=1) / days

        return np.maximum(recent(14), 0.85 * recent(56))

    def place_orders(self, t: int) -> None:
        d = self.dates[t]
        wd = d.isoweekday()
        avg = None
        for s in self.cat.suppliers:
            if wd not in s.order_weekdays:
                continue
            rng = self.R("order", t * 20 + s.index)
            if rng.random() < 0.08 and s.index != self.plan.overdue_supplier:
                continue
            if avg is None:
                avg = self.avg14(t)
            self._order_supplier(s.index, t, avg, rng)

    def _order_supplier(
        self, sup_idx: int, t: int, avg: np.ndarray, rng: np.random.Generator
    ) -> None:
        sup = self.cat.suppliers[sup_idx]
        d_ord = self.dates[t].toordinal()
        wait = max(0.0, (7.0 / len(sup.delivery_weekdays) - 1.0) / 2.0)
        review = 7.0 / len(sup.order_weekdays)
        cands: list[tuple[float, int, int]] = []
        direct: list[tuple[float, int, int]] = []
        for prod in self.cat.products:
            p = prod.index
            if prod.supplier != sup_idx:
                continue
            if p in self.plan.launch_idx and t < self.plan.launch_idx[p] - 5:
                continue
            if self.blocked(p, t):
                continue
            a = float(avg[p])
            if a <= 0:
                continue
            lead = self.lead(p) + wait
            position = self.sellable(p, d_ord) + self.incoming[p]
            rop = a * (lead + review + self.rop_extra) * float(rng.lognormal(0.0, 0.25))
            if position >= rop:
                continue
            target = a * (lead + review + self.target_extra) * float(rng.lognormal(0.0, 0.25))
            need = max(1.0, target - position)
            packs = max(
                math.ceil(need / prod.pack_size),
                math.ceil(prod.moq_units / prod.pack_size) if prod.moq_units else 1,
            )
            if rng.random() < 0.05:
                packs = max(1, round(packs * float(rng.uniform(0.6, 1.4))))
            qty = packs * prod.pack_size
            urgency = position / a
            (direct if not prod.has_term else cands).append((urgency, p, qty))
        for _urgency, p, qty in sorted(direct):
            self._direct_purchase(p, qty, t)
        if not cands:
            return
        cands.sort()
        if self.profile.key == "fmcg_a":
            values = [q * int(self.tl.cost[p, t]) / 100.0 for _, p, q in cands]
            cap = 0.70 * sum(values)
            kept, running = [], 0.0
            for item, value in zip(cands, values, strict=True):
                if kept and running + value > cap:
                    continue
                kept.append(item)
                running += value
            cands = kept
        total = sum(q * int(self.tl.cost[p, t]) / 100.0 for _, p, q in cands)
        mov = sup.min_order_value or 0
        if total < mov:
            filler = sorted(
                (
                    p
                    for p in range(self.n)
                    if self.cat.products[p].supplier == sup_idx
                    and avg[p] > 0
                    and not self.blocked(p, t)
                ),
                key=lambda p: -avg[p],
            )
            chosen = {p: q for _, p, q in cands}
            for _ in range(4):
                if total >= mov:
                    break
                for p in filler:
                    if total >= mov:
                        break
                    prod = self.cat.products[p]
                    held = self.sellable(p, d_ord) + self.incoming[p] + chosen.get(p, 0)
                    if held + prod.pack_size > float(avg[p]) * TOP_UP_COVER_DAYS:
                        continue
                    chosen[p] = chosen.get(p, 0) + prod.pack_size
                    total += prod.pack_size * int(self.tl.cost[p, t]) / 100.0
            if total < mov:
                self.stats["orders_below_minimum"] += 1
                return
            cands = [(0.0, p, q) for p, q in chosen.items()]
        specs = [(p, q) for _, p, q in sorted(cands, key=lambda x: x[1])]
        self.make_po(sup_idx, t, specs)

    def place_launch_orders(self, t: int) -> None:
        for p, day in self.plan.launch_idx.items():
            if t == day - 5:
                prod = self.cat.products[p]
                rate = float(self.dem.lam[p, day + 1 : day + 22].mean())
                qty = max(prod.pack_size, math.ceil(rate * 24 / prod.pack_size) * prod.pack_size)
                self.make_po(prod.supplier, t, [(p, qty)], arrival_idx=day - 1, note="Launch stock")

    def place_bulk_orders(self, t: int) -> None:
        for bulk in self.bulk_by_order.get(t, []):
            prod = self.cat.products[bulk.product]
            window = self.dem.lam[bulk.product, t : min(self.T, t + 60)]
            rate = (
                float(window.mean())
                if window.size
                else float(self.dem.lam[bulk.product, -30:].mean())
            )
            if bulk.cover_days is not None:
                units = rate * bulk.cover_days
            else:
                units = rate * (bulk.remaining_days or 90) * (bulk.sell_through or 2.0)
            qty = max(prod.pack_size, math.ceil(units / prod.pack_size) * prod.pack_size)
            self.make_po(
                prod.supplier,
                t,
                [(bulk.product, qty)],
                arrival_idx=bulk.arrive_idx,
                bulk=bulk,
                note=bulk.note or None,
            )

    def _direct_purchase(self, p: int, qty: int, t: int) -> None:
        """Bought over the counter from a local vendor: a receipt with no order and no supplier term."""
        rng = self.R("delivery", 500_000 + t * 7 + p)
        prod = self.cat.products[p]
        cost = int(prod.mrp * 100 * float(rng.uniform(0.86, 0.9)))
        d = self.dates[t]
        receipt = self._open_receipt(
            prod.supplier,
            None,
            d,
            t,
            exception=True,
            note="Bought over the counter, no order placed",
        )
        self._receive_line(receipt, None, p, qty, cost, t, None)
        self._close_receipt(receipt, [(qty, cost)])
        self.stats["direct_purchases"] += 1

    # ------------------------------------------------------------------ receipts
    def _open_receipt(
        self,
        supplier: int,
        po: PO | None,
        d: date,
        t: int,
        exception: bool = False,
        note: str | None = None,
    ) -> list[Any]:
        key = f"{d:%y%m}"
        self.seq_receipt[key] += 1
        rid = self.next_id(K_RECEIPT)
        number = f"GR{key}-{self.seq_receipt[key]:04d}"
        row = [
            make_uuid(self.ti, K_RECEIPT, rid),
            self.tenant,
            self.sup_uuid[supplier],
            make_uuid(self.ti, K_PO, po.id) if po else None,
            number,
            d,
            f"INV-{self.cat.suppliers[supplier].code}-{rid:05d}",
            None,
            "posted",
            exception,
            note,
            self.at(t, 6 * 3600 + 1700),
        ]
        self.rows["goods_receipts"].append(row)
        return row

    def _close_receipt(self, receipt: list[Any], values: list[tuple[int, int]]) -> None:
        receipt[IDX["goods_receipts"]["invoice_total"]] = money(
            sum(round(q * c / 100.0) for q, c in values)
        )

    def _receive_line(
        self,
        receipt: list[Any],
        po_line: POLine | None,
        p: int,
        qty: int,
        cost: int,
        t: int,
        po: PO | None,
    ) -> None:
        prod = self.cat.products[p]
        d = self.dates[t]
        when = self.at(t, 6 * 3600 + 1800 + (p % 1200))
        batch: Batch | None = None
        if self.tracked[p]:
            remaining = None
            flags: set[str] | None = None
            frac = (0.6, 0.9) if self.kind == "fmcg" else (0.55, 0.90)
            if po is not None and po.bulk is not None:
                remaining = po.bulk.remaining_days
                flags = po.bulk.flags
            batch = self.new_batch(
                p, qty, d, t, cost, remaining_days=remaining, remaining_frac=frac, flags=flags
            )
        self.add_stock(p, batch, qty, cost)
        self.recv_today[p] = True
        rid = receipt[0]
        rl_id = self.next_id(K_RLINE)
        self.rows["receipt_lines"].append(
            [
                make_uuid(self.ti, K_RLINE, rl_id),
                self.tenant,
                rid,
                make_uuid(self.ti, K_POLINE, po_line.id) if po_line else None,
                self.p_uuid[p],
                make_uuid(self.ti, K_BATCH, batch.idx + 1) if batch else None,
                qty,
                self.c4(cost),
                money(self.mrp_at(p, t)) if prod.is_batch_tracked else None,
                when,
            ]
        )
        self.move(p, batch, "receipt", qty, cost, when, d, "receipt", str(rid), None, None)

    def process_arrivals(self, t: int) -> None:
        for kind, po in self.arrivals.pop(t, []):
            if kind == "arrive":
                self._arrive(po, t)
            elif kind == "backorder":
                self._backorder(po, t)
            else:
                self._close_po(po, t)

    def _arrive(self, po: PO, t: int) -> None:
        rng = self.R("delivery", 800_000 + t * 50 + po.id % 50)
        sup = self.cat.suppliers[po.supplier]
        d = self.dates[t]
        if rng.random() < 0.02 and po.bulk is None:
            self._cancel(po, t, "Supplier could not supply this order")
            return
        short_prob = 0.5 * (1 - sup.fill_rate) + 0.01
        plan_recv: list[tuple[POLine, int]] = []
        for line in po.lines:
            if self.blocked(line.product, t):
                recv = 0
            elif po.bulk is None and rng.random() < short_prob:
                recv = max(1, round(line.qty * float(rng.uniform(0.5, 0.95))))
            else:
                recv = line.qty
            plan_recv.append((line, recv))
        if not any(recv > 0 for _, recv in plan_recv):
            self._cancel(po, t, "Supplier could not supply this order")
            return
        receipt = self._open_receipt(po.supplier, po, d, t)
        values: list[tuple[int, int]] = []
        shorts: list[POLine] = []
        for line, recv in plan_recv:
            if recv < line.qty:
                shorts.append(line)
            if recv > 0:
                self._receive_line(receipt, line, line.product, recv, line.cost4, t, po)
                values.append((recv, line.cost4))
                line.received = recv
                self.rows["purchase_order_lines"][line.row][
                    IDX["purchase_order_lines"]["quantity_received"]
                ] = recv
                self.incoming[line.product] -= recv
        self._close_receipt(receipt, values)
        if shorts:
            if rng.random() < 0.4:
                po.backorder_idx = t + int(rng.integers(2, 8))
                if po.backorder_idx < self.T:
                    self.arrivals[po.backorder_idx].append(("backorder", po))
            else:
                for line in shorts:
                    self.incoming[line.product] -= line.qty - line.received
                if t + 14 < self.T:
                    self.arrivals[t + 14].append(("close", po))
            self._set_status(po, "partially_received")
        else:
            self._set_status(po, "received")

    def _cancel(self, po: PO, t: int, reason: str) -> None:
        ci = IDX["purchase_orders"]
        row = self.rows["purchase_orders"][po.row]
        row[ci["status"]] = "cancelled"
        row[ci["cancelled_at"]] = self.at(t, 9 * 3600)
        row[ci["cancel_reason"]] = reason
        for line in po.lines:
            self.incoming[line.product] -= line.qty - line.received
        po.status = "cancelled"

    def _backorder(self, po: PO, t: int) -> None:
        d = self.dates[t]
        todo = [(ln, ln.qty - ln.received) for ln in po.lines if ln.qty - ln.received > 0]
        can = [(ln, rest) for ln, rest in todo if not self.blocked(ln.product, t)]
        for ln, rest in todo:
            if self.blocked(ln.product, t):
                self.incoming[ln.product] -= rest
        if not can:
            self._set_status(po, "closed")
            return
        receipt = self._open_receipt(po.supplier, po, d, t)
        values: list[tuple[int, int]] = []
        for line, rest in can:
            self._receive_line(receipt, line, line.product, rest, line.cost4, t, po)
            values.append((rest, line.cost4))
            line.received = line.qty
            self.rows["purchase_order_lines"][line.row][
                IDX["purchase_order_lines"]["quantity_received"]
            ] = line.qty
            self.incoming[line.product] -= rest
        self._close_receipt(receipt, values)
        done = all(ln.received >= ln.qty for ln in po.lines)
        self._set_status(po, "received" if done else "closed")

    def _set_status(self, po: PO, status: str) -> None:
        po.status = status
        self.rows["purchase_orders"][po.row][IDX["purchase_orders"]["status"]] = status

    def _close_po(self, po: PO, t: int) -> None:
        if po.status == "partially_received":
            self._set_status(po, "closed")

    # ------------------------------------------------------------------ expiry, adjustments, counts
    def _adjust(
        self,
        p: int,
        batch: Batch | None,
        qty: int,
        mtype: str,
        reason: str,
        note: str,
        t: int,
        seconds: float,
    ) -> None:
        d = self.dates[t]
        when = self.at(t, seconds)
        cost = batch.cost4 if batch is not None else self.avg4[p]
        adj_id = self.next_id(K_ADJ)
        mv = self.move(
            p,
            batch,
            mtype,
            qty,
            cost,
            when,
            d,
            "adjustment",
            str(make_uuid(self.ti, K_ADJ, adj_id)),
            reason,
            note,
        )
        if batch is not None:
            batch.qty += qty
        else:
            self.stock[p] += qty
        self.total[p] += qty
        self.rows["stock_adjustments"].append(
            (
                make_uuid(self.ti, K_ADJ, adj_id),
                self.tenant,
                self.p_uuid[p],
                make_uuid(self.ti, K_BATCH, batch.idx + 1) if batch else None,
                qty,
                reason,
                note,
                d,
                mv,
                when,
            )
        )

    def process_expiry(self, t: int) -> None:
        for batch in self.writeoffs.pop(t, []):
            if batch.qty > 0:
                self._adjust(
                    batch.product,
                    batch,
                    -batch.qty,
                    "expiry_writeoff",
                    "expiry_writeoff",
                    "Expired stock written off",
                    t,
                    6 * 3600 + 3300,
                )
                self.rows["product_batches"][batch.row][IDX["product_batches"]["status"]] = "closed"
                self.stats["writeoff_events"] += 1
        for batch in self.sup_returns.pop(t, []):
            if batch.qty > 0 and batch.expiry > self.dates[t].toordinal():
                self.stats["supplier_return_value"] += batch.qty * batch.cost4 / 10000.0
                self._adjust(
                    batch.product,
                    batch,
                    -batch.qty,
                    "supplier_return",
                    "supplier_return",
                    "Returned to supplier before expiry",
                    t,
                    6 * 3600 + 3480,
                )
                self.rows["product_batches"][batch.row][IDX["product_batches"]["status"]] = "closed"
                self.stats["supplier_returns"] += 1

    def start_blackouts(self, t: int) -> None:
        """At small scales a supply gap would take months to empty the shelf, so the stock left at
        the start of the gap is written off as damaged (a leak in the store room). At full scale
        the shelf empties by itself within weeks and nothing is written off."""
        if self.scale >= 0.5:
            return
        d_ord = self.dates[t].toordinal()
        for p, (start, _resume) in self.plan.blackouts.items():
            if start != t:
                continue
            if self.tracked[p]:
                for batch in list(self.batches[p]):
                    if batch.qty > 0 and batch.expiry > d_ord:
                        self._adjust(
                            p,
                            batch,
                            -batch.qty,
                            "damage",
                            "damage",
                            "Stock damaged in a leak",
                            t,
                            21 * 3600,
                        )
            elif self.stock[p] > 0:
                self._adjust(
                    p,
                    None,
                    -self.stock[p],
                    "damage",
                    "damage",
                    "Stock damaged in a leak",
                    t,
                    21 * 3600,
                )

    def process_adjustments(self, t: int) -> None:
        rng = self.R("adjust", t + 1)
        hits = np.nonzero(rng.random(self.n) < self.p_dmg / 7.0)[0]
        found = np.nonzero(rng.random(self.n) < self.p_dmg / 14.0)[0]
        d_ord = self.dates[t].toordinal()
        for p in hits:
            p = int(p)
            qty = 1 if rng.random() < 0.8 else 2
            batch = (
                next((b for b in self.batches[p] if b.qty > 0 and b.expiry > d_ord), None)
                if self.tracked[p]
                else None
            )
            if self.tracked[p] and batch is None:
                continue
            have = batch.qty if batch else self.stock[p]
            qty = min(qty, have)
            if qty > 0:
                self._adjust(
                    p,
                    batch,
                    -qty,
                    "damage",
                    "damage",
                    "Broken during handling",
                    t,
                    21 * 3600 + 1800,
                )
        for p in found:
            p = int(p)
            batch = (
                next((b for b in self.batches[p] if b.qty > 0 and b.expiry > d_ord), None)
                if self.tracked[p]
                else None
            )
            if self.tracked[p] and batch is None:
                continue
            self._adjust(
                p,
                batch,
                int(rng.integers(1, 4)),
                "adjustment",
                "found",
                "Found while tidying the shelf",
                t,
                21 * 3600 + 2400,
            )

    def process_counts(self, t: int) -> None:
        if t not in self.count_days:
            return
        rng = self.R("counts", t + 1)
        d = self.dates[t]
        count_id = self.next_id(K_COUNT)
        c_uuid = make_uuid(self.ti, K_COUNT, count_id)
        late = t >= self.T - 50
        a_class = set(self.rev_rank[: max(10, self.n * 3 // 10)])
        chosen = [
            p
            for p in range(self.n)
            if (p in a_class or rng.random() < 0.15) and not (late and p in self.plan.stale_count)
        ]
        chosen = [
            p for p in chosen if (p not in self.plan.launch_idx or t >= self.plan.launch_idx[p])
        ]
        lines = 0
        when = self.at(t, 7 * 3600)
        for p in chosen:
            entries: list[tuple[Batch | None, int]]
            if self.tracked[p]:
                entries = [(b, b.qty) for b in self.batches[p] if b.qty > 0]
            else:
                entries = [(None, self.stock[p])] if self.stock[p] > 0 or self.total[p] > 0 else []
            for batch, system in entries:
                var = 0
                if rng.random() < 0.12:
                    var = int(rng.choice([-1, -1, -2, 1]))
                    var = max(var, -system)
                lines += 1
                self.rows["stock_count_lines"].append(
                    (
                        make_uuid(self.ti, K_CLINE, self.next_id(K_CLINE)),
                        self.tenant,
                        c_uuid,
                        self.p_uuid[p],
                        make_uuid(self.ti, K_BATCH, batch.idx + 1) if batch else None,
                        system,
                        system + var,
                    )
                )
                if var != 0:
                    cost = batch.cost4 if batch else self.avg4[p]
                    self.move(
                        p,
                        batch,
                        "count_correction",
                        var,
                        cost,
                        when,
                        d,
                        "stock_count",
                        str(c_uuid),
                        "count",
                        "Stock count difference",
                    )
                    if batch:
                        batch.qty += var
                    else:
                        self.stock[p] += var
                    self.total[p] += var
        self.rows["stock_counts"].append(
            (
                c_uuid,
                self.tenant,
                d,
                "posted",
                "Partial stock count",
                self.at(t, 7 * 3600 + 3000),
                when,
            )
        )
        self.stats["count_lines"] += lines

    # ------------------------------------------------------------------ sales
    def _take(self, p: int, want: int, d_ord: int) -> list[tuple[Batch | None, int]]:
        if not self.tracked[p]:
            take = min(want, self.stock[p])
            if take <= 0:
                return []
            self.stock[p] -= take
            self.total[p] -= take
            return [(None, take)]
        parts: list[tuple[Batch | None, int]] = []
        remaining = want
        for b in self.batches[p]:
            if remaining == 0:
                break
            if b.qty > 0 and b.expiry > d_ord:
                take = min(b.qty, remaining)
                b.qty -= take
                self.total[p] -= take
                parts.append((b, take))
                remaining -= take
        return parts

    def _customer_lines(self, t: int, rng: np.random.Generator) -> list[tuple[int, int]]:
        demand = self.dem.true_demand[:, t]
        cont = LINE_QTY_CONTINUE[self.kind]
        lines: list[tuple[int, int]] = []
        for p in np.nonzero(demand)[0]:
            units = int(demand[p])
            if units == 1:
                lines.append((int(p), 1))
                continue
            k = 1 + int(rng.binomial(units - 1, cont))
            if k == 1:
                lines.append((int(p), units))
                continue
            cuts = np.sort(rng.choice(units - 1, size=k - 1, replace=False) + 1)
            edges = [0, *[int(c) for c in cuts], units]
            lines.extend((int(p), edges[i + 1] - edges[i]) for i in range(k))
        return lines

    def run_sales(self, t: int) -> None:
        d = self.dates[t]
        d_ord = d.toordinal()
        rng = self.R("bills", t)
        lines = self._customer_lines(t, rng)
        if not lines:
            return
        order = rng.permutation(len(lines))
        mean_lines = self.profile.lines_per_bill
        bills: list[dict[int, int]] = []
        i = 0
        while i < len(order):
            size = 1 + int(rng.poisson(max(0.0, mean_lines * 1.07 - 1.0)))
            basket: dict[int, int] = {}
            for j in order[i : i + size]:
                p, q = lines[int(j)]
                basket[p] = basket.get(p, 0) + q
            bills.append(basket)
            i += size
        hours = FMCG_HOURS if self.kind == "fmcg" else MED_HOURS
        h_keys = np.array(list(hours))
        h_probs = np.array(list(hours.values()))
        h_probs = h_probs / h_probs.sum()
        picked = rng.choice(h_keys, size=len(bills), p=h_probs)
        secs = picked * 3600 + rng.integers(0, 3600, size=len(bills))
        pay_names, pay_p = PAYMENT[self.kind]
        pay = rng.choice(len(pay_names), size=len(bills), p=pay_p)
        void_draw = rng.random(len(bills))
        disc_draw = rng.random(len(bills))
        ret_rate = 0.003 if self.kind == "medical" else 0.009
        key = f"{d:%y%m}"
        promo_row = self.tl.promo[:, t]
        for b_idx in np.argsort(secs, kind="stable"):
            basket = bills[int(b_idx)]
            sold_at = self.at(t, int(secs[b_idx]))
            made: list[list[Any]] = []
            for p, want in basket.items():
                parts = self._take(p, want, d_ord)
                got = sum(q for _, q in parts)
                if got < want:
                    self.lost[p, t] += want - got
                if got == 0:
                    continue
                self.sold[p, t] += got
                price = int(self.tl.sell[p, t])
                promo = int(promo_row[p])
                for batch, q in parts:
                    self.line_seq += 1
                    gross = price * q
                    made.append([self.line_seq, p, batch, q, price, gross, promo])
            if not made:
                continue
            discount = 0
            if disc_draw[b_idx] < 0.02:
                discount = min(100 * int(rng.integers(1, 6)), (made[0][5] // 100 - 1) * 100)
                discount = max(discount, 0)
            self.seq_bill[key] += 1
            sale_no = self.next_id(K_SALE)
            sale_uuid = make_uuid(self.ti, K_SALE, sale_no)
            sale_str = str(sale_uuid)
            subtotal = sum(m[5] for m in made)
            tax_total = 0
            line_rows: list[list[Any]] = []
            for k, (line_id, p, batch, q, price, gross, promo) in enumerate(made):
                line_disc = discount if k == 0 else 0
                total = gross - line_disc
                rate = self.tax_pct[p]
                tax_total += (
                    0 if rate == 0 else (total * rate * 2 + (100 + rate)) // (2 * (100 + rate))
                )
                cost = batch.cost4 if batch is not None else self.avg4[p]
                mv = self.move(p, batch, "sale", -q, cost, sold_at, d, "sale", sale_str)
                row = [
                    line_id,
                    self.tenant,
                    sale_uuid,
                    self.p_uuid[p],
                    make_uuid(self.ti, K_BATCH, batch.idx + 1) if batch else None,
                    q,
                    money(price),
                    money(line_disc),
                    rate,
                    money(total),
                    self.promo_uuid[promo] if promo >= 0 else None,
                    0,
                    d,
                    sold_at,
                ]
                line_rows.append(row)
                made[k].extend([mv, cost, total])
            voided = void_draw[b_idx] < 0.0015
            sale_row = [
                sale_uuid,
                self.tenant,
                f"B{key}-{self.seq_bill[key]:05d}",
                d,
                sold_at,
                pay_names[int(pay[b_idx])],
                "void" if voided else "completed",
                money(subtotal),
                money(discount),
                money(tax_total),
                money(subtotal - discount),
                "Entered by mistake" if voided else None,
                sold_at + timedelta(minutes=3) if voided else None,
                "seed",
                sold_at,
            ]
            self.rows["sales"].append(sale_row)
            self.rows["sale_lines"].extend(line_rows)
            if voided:
                self.stats["voids"] += 1
                for _line_id, p, batch, q, _price, _gross, _promo, mv, cost, _total in made:
                    self.move(
                        p,
                        batch,
                        "void_reversal",
                        q,
                        cost,
                        sold_at,
                        d,
                        "void",
                        sale_str,
                        "void",
                        "Entered by mistake",
                        reverses=mv,
                    )
                    self.add_back(p, batch, q)
                    self.sold[p, t] -= q
                continue
            for k, (_line_id, p, batch, q, _price, _gross, _promo, _mv, cost, total) in enumerate(
                made
            ):
                if rng.random() < ret_rate:
                    offset = int(rng.choice(4, p=OFFSET_WEIGHTS))
                    if t + offset < self.T:
                        self.pending_returns[t + offset].append(
                            (line_rows[k], sale_row, p, batch, q, total, cost)
                        )

    def add_back(self, p: int, batch: Batch | None, qty: int) -> None:
        if batch is not None:
            batch.qty += qty
        else:
            self.stock[p] += qty
        self.total[p] += qty

    def process_returns(self, t: int) -> None:
        todo = self.pending_returns.pop(t, [])
        if not todo:
            return
        rng = self.R("returns", t)
        d = self.dates[t]
        d_ord = d.toordinal()
        key = f"{d:%y%m}"
        ci_sl = IDX["sale_lines"]
        for line_row, sale_row, p, batch, q, line_total, cost in todo:
            units = 1 if q == 1 or rng.random() < 0.7 else q
            roll = rng.random()
            disposition = "restock" if roll < 0.80 else ("damaged" if roll < 0.95 else "expired")
            if batch is not None and disposition == "restock":
                closed = (
                    self.rows["product_batches"][batch.row][IDX["product_batches"]["status"]]
                    == "closed"
                )
                if batch.expiry <= d_ord:
                    disposition = "expired"
                elif closed:
                    disposition = "damaged"
            when = self.at(t, int(rng.integers(9, 21)) * 3600 + int(rng.integers(0, 3600)))
            self.seq_return[key] += 1
            rid = self.next_id(K_RETURN)
            r_uuid = make_uuid(self.ti, K_RETURN, rid)
            refund = (line_total * units * 2 + q) // (2 * q)
            self.rows["sale_returns"].append(
                (
                    r_uuid,
                    self.tenant,
                    sale_row[0],
                    f"R{key}-{self.seq_return[key]:04d}",
                    d,
                    str(rng.choice(RETURN_REASONS)),
                    "posted",
                    money(refund),
                    when,
                )
            )
            self.rline_seq += 1
            self.rows["sale_return_lines"].append(
                (
                    self.rline_seq,
                    self.tenant,
                    r_uuid,
                    line_row[0],
                    self.p_uuid[p],
                    line_row[ci_sl["batch_id"]],
                    units,
                    money(refund),
                    disposition,
                )
            )
            line_row[ci_sl["returned_qty"]] = units
            self.move(
                p,
                batch,
                "return_in",
                units,
                cost,
                when,
                d,
                "sale_return",
                str(r_uuid),
                disposition,
                "Customer return",
            )
            self.add_back(p, batch, units)
            if disposition != "restock":
                mtype = "damage" if disposition == "damaged" else "expiry_writeoff"
                self.move(
                    p,
                    batch,
                    mtype,
                    -units,
                    cost,
                    when,
                    d,
                    "sale_return",
                    str(r_uuid),
                    "return",
                    "Customer return",
                )
                self.add_back(p, batch, -units)
            self.stats["returns"] += 1

    # ------------------------------------------------------------------ the loop
    def _end_of_day(self, t: int, open_total: list[int]) -> None:
        for p in range(self.n):
            self.closing[p, t] = self.total[p]
            launched = p not in self.plan.launch_idx or t >= self.plan.launch_idx[p]
            out = launched and open_total[p] == 0 and not self.recv_today[p]
            if out:
                self.out_all_day[p, t] = True
                if self.run_start[p] < 0:
                    self.run_start[p] = t
            elif self.run_start[p] >= 0:
                self._close_run(p, self.run_start[p], t - 1, ended=True)
                self.run_start[p] = -1
            self.recv_today[p] = False

    def _close_run(self, p: int, start: int, end: int, ended: bool) -> None:
        if end - start + 1 < 2:
            return
        rng = self.R("stockout", p * 1000 + start)
        forced = self.plan.force_recorded.get(p)
        record = forced if forced is not None else bool(rng.random() < 0.6)
        if not record:
            return
        sid = self.next_id(K_STOCKOUT)
        self.rows["stockout_intervals"].append(
            (
                make_uuid(self.ti, K_STOCKOUT, sid),
                self.tenant,
                self.p_uuid[p],
                self.dates[start],
                self.dates[end] if ended else None,
                "recorded",
                "Noted by the owner",
                self.at(min(end + 1, self.T - 1), 18 * 3600),
            )
        )

    def run(self) -> TenantData:
        for bulk in self.plan.bulk_orders:
            lead = self.lead(bulk.product)
            order_idx = max(0, bulk.arrive_idx - lead)
            if bulk.arrive_idx >= 3:
                self.bulk_by_order[order_idx].append(bulk)
        self.open_stock()
        for t in range(self.T):
            open_total = list(self.total)
            self.process_arrivals(t)
            self.process_expiry(t)
            self.start_blackouts(t)
            self.process_counts(t)
            self.place_launch_orders(t)
            self.place_bulk_orders(t)
            self.place_orders(t)
            if (
                self.plan.overdue_supplier is not None
                and t == self.T - 14
                and not self.overdue_done
            ):
                self._force_overdue(t)
            self.run_sales(t)
            self.process_returns(t)
            self.process_adjustments(t)
            self._end_of_day(t, open_total)
        for p in range(self.n):
            if self.run_start[p] >= 0:
                self._close_run(p, self.run_start[p], self.T - 1, ended=False)
        return self._finish()

    def _force_overdue(self, t: int) -> None:
        sup = self.plan.overdue_supplier
        if sup is None:
            return
        prods = [p for p in self.cat.products if p.supplier == sup][:3]
        if prods:
            self.make_po(sup, t, [(p.index, p.pack_size * 2) for p in prods], stuck=True)

    def _finish(self) -> TenantData:
        balances: dict[tuple[int, int | None], tuple[int, int, datetime | None]] = {}
        for p in range(self.n):
            if self.tracked[p]:
                for b in self.batches[p]:
                    balances[(p, b.idx)] = (b.qty, b.cost4, self.last_move.get((p, b.idx)))
            elif (p, None) in self.last_move:
                balances[(p, None)] = (self.stock[p], self.avg4[p], self.last_move[(p, None)])
        info = [
            {"idx": b.idx, "product": b.product, "expiry": b.expiry, "qty": b.qty, "cost4": b.cost4}
            for b in self.all_batches
        ]
        cogs_day = (self.sold * self.tl.cost).sum(axis=0) / 10000.0
        cogs_by_week = [float(cogs_day[i : i + 7].sum()) for i in range(0, self.T - 6, 7)]
        self.stats["movements"] = len(self.rows["inventory_movements"])
        return TenantData(
            rows=self.rows,
            true_demand=self.dem.true_demand,
            event_mult=self.dem.event_mult,
            promo_mult=self.dem.promo_mult,
            closing=self.closing,
            sold=self.sold,
            lost=self.lost,
            out_all_day=self.out_all_day,
            final_balances=balances,
            batch_info=info,
            weekly_cogs=cogs_by_week,
            stats=dict(self.stats),
            movement_count=len(self.rows["inventory_movements"]),
        )
