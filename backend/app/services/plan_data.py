"""Loads everything the engine needs for one tenant at one plan date.

State is rebuilt from the ledger with `business_date < as_of`, not read from the cached
balances, so a plan for a given Monday always shows the stock at its data cutoff, even when it
is regenerated later or backfilled for a past week.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engine.calendar import CalendarEvent
from app.engine.constants import TRAINING_DAYS
from app.engine.event_effects import EffectRecord, PromoOccurrence
from app.engine.inputs import (
    BatchInfo,
    IncomingLine,
    ProductInfo,
    SettingsInfo,
    SupplierInfo,
    TermInfo,
)
from app.engine.rollup import STATE_NAMES
from app.engine.types import BoolArray, FloatArray, IntArray

DEFAULT_WEIGHTS = {"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}


@dataclass(frozen=True)
class TenantInfo:
    id: uuid.UUID
    slug: str
    name: str
    business_type: str
    is_synthetic: bool


@dataclass(frozen=True)
class History:
    """Products by days, ending the day before the plan date."""

    start: date
    product_ids: list[uuid.UUID]
    units: FloatArray
    codes: IntArray
    promo: BoolArray
    revenue: FloatArray

    @property
    def n_days(self) -> int:
        return int(self.units.shape[1])

    @property
    def index(self) -> dict[uuid.UUID, int]:
        return {pid: i for i, pid in enumerate(self.product_ids)}


class PlanLoader:
    def __init__(self, session: Session, tenant_id: uuid.UUID, as_of: date) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of = as_of

    def _rows(self, sql: str, **params: Any) -> list[Any]:
        return list(
            self.session.execute(
                text(sql), {"t": self.tenant_id, "as_of": self.as_of, **params}
            ).all()
        )

    # ------------------------------------------------------------------ tenant

    def tenant(self) -> TenantInfo:
        row = self._rows(
            "SELECT id, slug, name, business_type, is_synthetic FROM tenants WHERE id = :t"
        )[0]
        return TenantInfo(row[0], row[1], row[2], row[3], bool(row[4]))

    def settings(self) -> SettingsInfo:
        rows = self._rows("SELECT * FROM business_settings WHERE tenant_id = :t")
        if not rows:
            return SettingsInfo()
        m = rows[0]._mapping
        stored = {k: float(v) for k, v in (m["priority_weights"] or {}).items()}
        weights = {**DEFAULT_WEIGHTS, **stored}
        return SettingsInfo(
            weekly_budget=m["weekly_budget"],
            service_level=float(m["service_level"]),
            review_period_days=int(m["review_period_days"]),
            default_lead_time_days=int(m["default_lead_time_days"]),
            near_expiry_days=int(m["near_expiry_days"]),
            nonmoving_days=int(m["nonmoving_days"]),
            slow_cover_days=int(m["slow_cover_days"]),
            excess_horizon_days=int(m["excess_horizon_days"]),
            forecast_horizon_days=int(m["forecast_horizon_days"]),
            backtest_origins=int(m["backtest_origins"]),
            stale_count_days=int(m["stale_count_days"]),
            sellable_shelf_life_fraction=float(m["sellable_shelf_life_fraction"]),
            censor_policy=str(m["censor_policy"]),
            pack_rounding=str(m["pack_rounding"]),
            priority_weights=weights,
            apply_festival_lead_padding=bool(m["apply_festival_lead_padding"]),
        )

    def suppliers(self) -> dict[uuid.UUID, SupplierInfo]:
        out: dict[uuid.UUID, SupplierInfo] = {}
        for r in self._rows(
            """
            SELECT id, code, name, default_lead_time_days, delivery_weekdays, min_order_value,
                   accepts_expiry_returns, expiry_return_window_days
            FROM suppliers WHERE tenant_id = :t
            """
        ):
            days = tuple(int(d) for d in r[4]) if r[4] else None
            out[r[0]] = SupplierInfo(r[0], r[1], r[2], r[3], days, r[5], bool(r[6]), r[7])
        return out

    # ------------------------------------------------------------------ calendar

    def calendar_events(self) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                slug=r[0],
                event_key=r[1],
                name=r[2],
                kind=r[3],
                start=r[4],
                end=r[5],
                pre_days=int(r[6]),
                post_days=int(r[7]),
                delay_days=int(r[8]),
                is_verified=bool(r[9]),
                affects_hours=bool(r[10]),
            )
            for r in self._rows(
                """
                SELECT slug, event_key, name, kind, start_date, end_date, pre_window_days,
                       post_window_days, delivery_delay_days, is_verified, affects_hours
                FROM calendar_events WHERE is_active ORDER BY start_date, event_key
                """
            )
        ]

    def promotions(
        self, product_index: dict[uuid.UUID, int], category_keys: dict[uuid.UUID, str]
    ) -> list[PromoOccurrence]:
        out: list[PromoOccurrence] = []
        for r in self._rows(
            "SELECT product_id, category_id, starts_on, ends_on "
            "FROM promotions WHERE tenant_id = :t"
        ):
            if r[0] is not None and r[0] in product_index:
                out.append(PromoOccurrence(r[2], r[3], product_index[r[0]], None))
            elif r[1] is not None and r[1] in category_keys:
                out.append(PromoOccurrence(r[2], r[3], None, category_keys[r[1]]))
        return out

    def stored_effects(self) -> tuple[list[EffectRecord], Any]:
        """Effect rows saved by an earlier run, and the time the newest was computed."""
        records: list[EffectRecord] = []
        newest = None
        for r in self._rows(
            """
            SELECT event_key, category_id, "window", multiplier, origin, n_occurrences,
                   n_products, consistency, evidence, confidence, is_applied, computed_at
            FROM event_category_effects WHERE tenant_id = :t
            """
        ):
            records.append(
                EffectRecord(
                    event_key=r[0],
                    category_key=str(r[1]),
                    window=r[2],
                    multiplier=float(r[3]),
                    origin=r[4],
                    n_occurrences=int(r[5]),
                    n_products=int(r[6]),
                    consistency=float(r[7]) if r[7] is not None else None,
                    evidence=dict(r[8] or {}),
                    confidence=r[9],
                    is_applied=bool(r[10]),
                )
            )
            newest = r[11] if newest is None or r[11] > newest else newest
        return records, newest

    # ------------------------------------------------------------------ history

    def history(self, days: int = TRAINING_DAYS) -> History:
        end = self.as_of - timedelta(days=1)
        start = self.as_of - timedelta(days=days)
        ids = [r[0] for r in self._rows("SELECT id FROM products WHERE tenant_id = :t ORDER BY id")]
        index = {pid: i for i, pid in enumerate(ids)}
        first = self._rows("SELECT MIN(stat_date) FROM daily_product_stats WHERE tenant_id = :t")[
            0
        ][0]
        if first is not None and first > start:
            start = first
        n = max((end - start).days + 1, 0)
        units = np.zeros((len(ids), n), dtype=np.float64)
        revenue = np.zeros((len(ids), n), dtype=np.float64)
        codes = np.full((len(ids), n), STATE_NAMES.index("unknown"), dtype=np.int64)
        promo = np.zeros((len(ids), n), dtype=np.bool_)
        code_of = {name: i for i, name in enumerate(STATE_NAMES)}
        for r in self._rows(
            """
            SELECT product_id, stat_date, units_sold - units_returned, revenue,
                   availability_state, promo_active
            FROM daily_product_stats
            WHERE tenant_id = :t AND stat_date BETWEEN :s AND :e
            """,
            s=start,
            e=end,
        ):
            p = index.get(r[0])
            if p is None:
                continue
            d = (r[1] - start).days
            units[p, d] = float(r[2])
            revenue[p, d] = float(r[3])
            codes[p, d] = code_of[r[4]]
            promo[p, d] = bool(r[5])
        return History(start, ids, units, codes, promo, revenue)

    # ------------------------------------------------------------------ products

    def products(
        self, history: History, suppliers: dict[uuid.UUID, SupplierInfo]
    ) -> list[ProductInfo]:
        as_of = self.as_of
        terms: dict[uuid.UUID, TermInfo] = {}
        term_from: dict[uuid.UUID, date] = {}
        by_product: dict[uuid.UUID, list[Any]] = defaultdict(list)
        for r in self._rows(
            """
            SELECT product_id, supplier_id, purchase_price, pack_size, moq_units, lead_time_days,
                   effective_from, effective_to, is_primary
            FROM supplier_product_terms WHERE tenant_id = :t ORDER BY effective_from
            """
        ):
            by_product[r[0]].append(r)
            if (
                r[8]
                and r[6] <= as_of
                and (r[7] is None or r[7] >= as_of)
                and (r[0] not in term_from or r[6] >= term_from[r[0]])
            ):
                terms[r[0]] = TermInfo(r[1], r[2], r[3], r[4], r[5])
                term_from[r[0]] = r[6]
        previous: dict[uuid.UUID, tuple[Decimal, ...]] = {}
        for pid, rows in by_product.items():
            term = terms.get(pid)
            if term is None:
                continue
            earlier = [r[2] for r in rows if r[1] == term.supplier_id and r[6] < term_from[pid]]
            if earlier:
                previous[pid] = (earlier[-1],)

        prices = {
            r[0]: (r[1], r[2])
            for r in self._rows(
                """
                SELECT DISTINCT ON (product_id) product_id, selling_price, mrp FROM product_prices
                WHERE tenant_id = :t AND effective_from <= :as_of
                ORDER BY product_id, effective_from DESC
                """
            )
        }
        batch_meta = {
            r[0]: r
            for r in self._rows(
                """
                SELECT id, product_id, batch_no, expiry_date, unit_cost, status
                FROM product_batches WHERE tenant_id = :t
                """
            )
        }
        batches: dict[uuid.UUID, list[BatchInfo]] = defaultdict(list)
        for pid, batch_id, qty in self._rows(
            """
            SELECT product_id, batch_id, SUM(quantity_delta) FROM inventory_movements
            WHERE tenant_id = :t AND business_date < :as_of
            GROUP BY product_id, batch_id HAVING SUM(quantity_delta) <> 0
            """
        ):
            meta = batch_meta.get(batch_id) if batch_id else None
            batches[pid].append(
                BatchInfo(
                    batch_id=batch_id,
                    batch_no=meta[2] if meta else None,
                    qty=float(qty),
                    expiry_date=meta[3] if meta else None,
                    unit_cost=meta[4] if meta else Decimal(0),
                    status=meta[5] if meta else "active",
                )
            )
        avg_cost = {
            r[0]: r[1]
            for r in self._rows(
                """
                SELECT product_id, MAX(avg_unit_cost) FROM stock_balances
                WHERE tenant_id = :t GROUP BY product_id
                """
            )
        }
        incoming: dict[uuid.UUID, list[IncomingLine]] = defaultdict(list)
        for r in self._rows(
            """
            SELECT pl.product_id, po.id, po.po_number, po.supplier_id, po.expected_date,
                   pl.quantity_ordered - COALESCE(rec.qty, 0) AS qty_open
            FROM purchase_order_lines pl
            JOIN purchase_orders po ON po.tenant_id = pl.tenant_id AND po.id = pl.po_id
            LEFT JOIN (
                SELECT rl.po_line_id, SUM(rl.quantity_received) AS qty
                FROM receipt_lines rl
                JOIN goods_receipts g ON g.tenant_id = rl.tenant_id AND g.id = rl.receipt_id
                WHERE rl.tenant_id = :t AND g.status = 'posted' AND g.received_on < :as_of
                GROUP BY rl.po_line_id
            ) rec ON rec.po_line_id = pl.id
            WHERE pl.tenant_id = :t AND po.status <> 'draft'
              AND COALESCE((po.sent_at AT TIME ZONE 'Asia/Kolkata')::date, po.order_date) < :as_of
              AND (po.status <> 'cancelled'
                   OR (po.cancelled_at AT TIME ZONE 'Asia/Kolkata')::date >= :as_of)
              AND po.status <> 'closed'
              AND pl.quantity_ordered - COALESCE(rec.qty, 0) > 0
            """
        ):
            incoming[r[0]].append(IncomingLine(r[1], r[2], r[3], float(r[5]), r[4]))
        last_count = {
            r[0]: r[1]
            for r in self._rows(
                """
                SELECT l.product_id, MAX(c.count_date)
                FROM stock_count_lines l
                JOIN stock_counts c ON c.tenant_id = l.tenant_id AND c.id = l.count_id
                WHERE l.tenant_id = :t AND c.status = 'posted' AND c.count_date < :as_of
                  AND l.counted_qty IS NOT NULL
                GROUP BY l.product_id
                """
            )
        }
        last_receipt: dict[uuid.UUID, date] = {}
        fallback_supplier: dict[uuid.UUID, uuid.UUID] = {}
        for r in self._rows(
            """
            SELECT DISTINCT ON (rl.product_id) rl.product_id, g.received_on, g.supplier_id
            FROM receipt_lines rl
            JOIN goods_receipts g ON g.tenant_id = rl.tenant_id AND g.id = rl.receipt_id
            WHERE rl.tenant_id = :t AND g.status = 'posted' AND g.received_on < :as_of
            ORDER BY rl.product_id, g.received_on DESC
            """
        ):
            last_receipt[r[0]], fallback_supplier[r[0]] = r[1], r[2]

        idx = history.index
        first_seen: dict[uuid.UUID, date] = {}
        open_codes = {STATE_NAMES.index("unknown"), STATE_NAMES.index("not_launched")}
        for pid, i in idx.items():
            row = history.codes[i]
            hit = np.nonzero(~np.isin(row, list(open_codes)))[0]
            if hit.size:
                first_seen[pid] = history.start + timedelta(days=int(hit[0]))

        out: list[ProductInfo] = []
        for r in self._rows(
            """
            SELECT p.id, p.sku, p.name, p.category_id, c.slug, c.name, p.is_active,
                   p.is_batch_tracked, p.shelf_life_days, p.min_stock_qty, p.is_seasonal,
                   p.launched_on, p.selling_price, p.mrp, p.base_unit, p.pack_label
            FROM products p
            JOIN categories c ON c.tenant_id = p.tenant_id AND c.id = p.category_id
            WHERE p.tenant_id = :t ORDER BY p.id
            """
        ):
            pid = r[0]
            price = prices.get(pid)
            term = terms.get(pid)
            has_term_supplier = term is not None and term.supplier_id in suppliers
            out.append(
                ProductInfo(
                    id=pid,
                    sku=r[1],
                    name=r[2],
                    category_id=r[3],
                    category_slug=r[4],
                    category_name=r[5],
                    is_active=bool(r[6]),
                    is_batch_tracked=bool(r[7]),
                    shelf_life_days=r[8],
                    min_stock_qty=float(r[9]),
                    is_seasonal=bool(r[10]),
                    launched_on=r[11],
                    first_seen=first_seen.get(pid),
                    selling_price=price[0] if price else r[12],
                    mrp=price[1] if price else r[13],
                    base_unit=r[14],
                    pack_label=r[15],
                    avg_cost=avg_cost.get(pid) or Decimal(0),
                    term=term if has_term_supplier else None,
                    fallback_supplier_id=fallback_supplier.get(pid),
                    previous_term_prices=previous.get(pid, ()),
                    batches=tuple(batches.get(pid, ())),
                    incoming=tuple(incoming.get(pid, ())),
                    last_count_date=last_count.get(pid),
                    last_receipt_date=last_receipt.get(pid),
                )
            )
        return out
