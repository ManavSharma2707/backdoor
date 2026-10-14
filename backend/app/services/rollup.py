"""Builds `daily_product_stats` from the ledger, sales and returns.

The rules live in `app/engine/rollup.py`. This service reads the aggregates, writes the rows and
keeps the inferred stockout intervals in step. It can rebuild any range, and the incremental
run re-computes the last days again, because a recorded stockout or a late return can change a
day that was already rolled up.
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

from app.core.logging import get_logger
from app.engine import rollup as rules
from app.engine.constants import UNRECORDED_STOCKOUT_DAYS
from app.engine.types import BoolArray, IntArray

log = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 14
MILLI = 1000


@dataclass(frozen=True)
class RollupResult:
    start: date | None
    end: date | None
    rows: int
    products: int
    inferred_intervals: int


def _milli(value: Decimal | int | None) -> int:
    return round(Decimal(value or 0) * MILLI)


def _qty(milli: int) -> Decimal:
    return Decimal(milli).scaleb(-3)


class RollupService:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ public

    def history_start(self) -> date | None:
        """The day after the first ledger entry (the opening balance has no stats row)."""
        first = self.session.execute(
            text("SELECT MIN(business_date) FROM inventory_movements WHERE tenant_id = :t"),
            {"t": self.tenant_id},
        ).scalar_one()
        return first + timedelta(days=1) if first else None

    def last_rolled(self) -> date | None:
        value: date | None = self.session.execute(
            text("SELECT MAX(stat_date) FROM daily_product_stats WHERE tenant_id = :t"),
            {"t": self.tenant_id},
        ).scalar_one()
        return value

    def rebuild(self, start: date | None, end: date) -> RollupResult:
        """Delete and re-create every row from `start` (default: whole history) to `end`."""
        first = self.history_start()
        if first is None or end < first:
            return RollupResult(None, None, 0, 0, 0)
        begin = max(start, first) if start else first
        result = self._write(self._product_ids(), begin, end)
        return self._with_intervals(result, end)

    def update(self, through: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> RollupResult:
        """Bring the table up to `through`. New products are rolled over their whole history."""
        first = self.history_start()
        if first is None or through < first:
            return RollupResult(None, None, 0, 0, 0)
        last = self.last_rolled()
        if last is None:
            return self._with_intervals(self._write(self._product_ids(), first, through), through)
        missing = self._products_without_stats()
        rows = products = 0
        if missing:
            res = self._write(missing, first, through)
            rows, products = res.rows, res.products
        start = min(max(first, last - timedelta(days=lookback_days - 1)), through)
        res = self._write(self._product_ids(exclude=set(missing)), start, through)
        merged = RollupResult(
            first if missing else start, through, rows + res.rows, products + res.products, 0
        )
        return self._with_intervals(merged, through)

    # ------------------------------------------------------------------ reading

    def _product_ids(self, exclude: set[uuid.UUID] | None = None) -> list[uuid.UUID]:
        rows = self.session.execute(
            text("SELECT id FROM products WHERE tenant_id = :t ORDER BY id"), {"t": self.tenant_id}
        ).scalars()
        return [pid for pid in rows if not exclude or pid not in exclude]

    def _products_without_stats(self) -> list[uuid.UUID]:
        rows = self.session.execute(
            text(
                """
                SELECT p.id FROM products p
                WHERE p.tenant_id = :t AND NOT EXISTS (
                    SELECT 1 FROM daily_product_stats s
                    WHERE s.tenant_id = p.tenant_id AND s.product_id = p.id)
                ORDER BY p.id
                """
            ),
            {"t": self.tenant_id},
        ).scalars()
        return list(rows)

    def _grid(
        self,
        table_sql: str,
        params: dict[str, Any],
        index: dict[uuid.UUID, int],
        n_days: int,
        start: date,
        columns: int,
    ) -> tuple[IntArray, ...]:
        arrays = [np.zeros((len(index), n_days), dtype=np.int64) for _ in range(columns)]
        for row in self.session.execute(text(table_sql), params):
            p = index.get(row[0])
            if p is None:
                continue
            d = (row[1] - start).days
            if 0 <= d < n_days:
                for k in range(columns):
                    arrays[k][p, d] = _milli(row[2 + k])
        return tuple(arrays)

    # ------------------------------------------------------------------ writing

    def _with_intervals(self, result: RollupResult, end: date) -> RollupResult:
        found = self._infer_intervals(end)
        return RollupResult(result.start, result.end, result.rows, result.products, found)

    def _write(self, product_ids: list[uuid.UUID], start: date, end: date) -> RollupResult:
        tid = self.tenant_id
        if not product_ids:
            return RollupResult(start, end, 0, 0, 0)
        n_days = (end - start).days + 1
        index = {pid: i for i, pid in enumerate(product_ids)}
        scope = {"t": tid, "s": start, "e": end}

        meta = {
            row[0]: (row[1], row[2])
            for row in self.session.execute(
                text("SELECT id, category_id, launched_on FROM products WHERE tenant_id = :t"),
                {"t": tid},
            )
        }
        pre_rows = self.session.execute(
            text(
                """
                SELECT product_id, SUM(quantity_delta) FROM inventory_movements
                WHERE tenant_id = :t AND business_date < :s GROUP BY product_id
                """
            ),
            scope,
        ).all()
        pre = np.zeros(len(product_ids), dtype=np.int64)
        for pid, qty in pre_rows:
            if pid in index:
                pre[index[pid]] = _milli(qty)
        first_day: list[date | None] = [None] * len(product_ids)
        for pid, day in self.session.execute(
            text(
                """
                SELECT product_id, MIN(business_date) FROM inventory_movements
                WHERE tenant_id = :t GROUP BY product_id
                """
            ),
            scope,
        ):
            if pid in index:
                first_day[index[pid]] = day

        net, receipts = self._grid(
            """
            SELECT product_id, business_date, SUM(quantity_delta),
                   COALESCE(SUM(quantity_delta) FILTER (WHERE movement_type = 'receipt'), 0)
            FROM inventory_movements
            WHERE tenant_id = :t AND business_date BETWEEN :s AND :e
            GROUP BY product_id, business_date
            """,
            scope,
            index,
            n_days,
            start,
            2,
        )
        sold_qty, sold_rev = self._grid(
            """
            SELECT l.product_id, l.business_date, SUM(l.quantity), SUM(l.line_total)
            FROM sale_lines l
            JOIN sales s ON s.tenant_id = l.tenant_id AND s.id = l.sale_id
            WHERE l.tenant_id = :t AND l.business_date BETWEEN :s AND :e AND s.status = 'completed'
            GROUP BY l.product_id, l.business_date
            """,
            scope,
            index,
            n_days,
            start,
            2,
        )
        (returned,) = self._grid(
            """
            SELECT rl.product_id, r.business_date, SUM(rl.quantity)
            FROM sale_return_lines rl
            JOIN sale_returns r ON r.tenant_id = rl.tenant_id AND r.id = rl.return_id
            WHERE rl.tenant_id = :t AND r.business_date BETWEEN :s AND :e
              AND r.status = 'posted' AND rl.disposition = 'restock'
            GROUP BY rl.product_id, r.business_date
            """,
            scope,
            index,
            n_days,
            start,
            1,
        )

        opening, closing = rules.running_balances(pre, net)
        intervals: list[list[rules.Interval]] = [[] for _ in product_ids]
        for pid, lo, hi in self.session.execute(
            text(
                """
                SELECT product_id, start_date, end_date FROM stockout_intervals
                WHERE tenant_id = :t AND source = 'recorded'
                  AND start_date <= :e AND (end_date IS NULL OR end_date >= :s)
                """
            ),
            scope,
        ):
            if pid in index:
                intervals[index[pid]].append(rules.Interval(lo, hi))
        forced = rules.forced_by_intervals(n_days, start, intervals)
        codes = rules.classify_availability(
            start=start,
            opening=opening,
            closing=closing,
            receipts=receipts,
            units_sold=sold_qty,
            launched_on=[meta[pid][1] for pid in product_ids],
            first_ledger_day=first_day,
            forced=forced,
        )
        censored = rules.is_censored(codes)
        promo = self._promo_mask(
            product_ids, {pid: meta[pid][0] for pid in product_ids}, start, end, n_days, index
        )
        events = self._event_keys(start, n_days)

        self.session.execute(
            text(
                """
                DELETE FROM daily_product_stats
                WHERE tenant_id = :t AND stat_date BETWEEN :s AND :e
                  AND product_id = ANY(:ids)
                """
            ),
            {**scope, "ids": product_ids},
        )
        n_rows = self._copy_rows(
            product_ids,
            start,
            n_days,
            opening,
            closing,
            receipts,
            sold_qty,
            sold_rev,
            returned,
            codes,
            censored,
            promo,
            events,
        )
        log.info(
            "rollup.done",
            tenant_id=str(tid),
            start=start.isoformat(),
            end=end.isoformat(),
            rows=n_rows,
            products=len(product_ids),
        )
        return RollupResult(start, end, n_rows, len(product_ids), 0)

    def _promo_mask(
        self,
        product_ids: list[uuid.UUID],
        category_of: dict[uuid.UUID, uuid.UUID],
        start: date,
        end: date,
        n_days: int,
        index: dict[uuid.UUID, int],
    ) -> BoolArray:
        mask = np.zeros((len(product_ids), n_days), dtype=np.bool_)
        by_category: dict[uuid.UUID, list[int]] = defaultdict(list)
        for pid in product_ids:
            by_category[category_of[pid]].append(index[pid])
        rows = self.session.execute(
            text(
                """
                SELECT product_id, category_id, starts_on, ends_on FROM promotions
                WHERE tenant_id = :t AND starts_on <= :e AND ends_on >= :s
                """
            ),
            {"t": self.tenant_id, "s": start, "e": end},
        )
        for product_id, category_id, lo, hi in rows:
            a = max((lo - start).days, 0)
            b = min((hi - start).days, n_days - 1)
            targets = (
                [index[product_id]] if product_id in index else by_category.get(category_id, [])
            )
            for p in targets:
                mask[p, a : b + 1] = True
        return mask

    def _event_keys(self, start: date, n_days: int) -> list[list[str]]:
        keys: list[set[str]] = [set() for _ in range(n_days)]
        rows = self.session.execute(
            text(
                """
                SELECT event_key, start_date - pre_window_days, end_date + post_window_days
                FROM calendar_events WHERE is_active
                """
            )
        )
        for key, lo, hi in rows:
            a = max((lo - start).days, 0)
            b = min((hi - start).days, n_days - 1)
            for d in range(a, b + 1):
                keys[d].add(key)
        return [sorted(k) for k in keys]

    def _copy_rows(
        self,
        product_ids: list[uuid.UUID],
        start: date,
        n_days: int,
        opening: IntArray,
        closing: IntArray,
        receipts: IntArray,
        sold_qty: IntArray,
        sold_rev: IntArray,
        returned: IntArray,
        codes: IntArray,
        censored: BoolArray,
        promo: BoolArray,
        events: list[list[str]],
    ) -> int:
        cursor = self.session.connection().connection.cursor()
        count = 0
        with cursor.copy(
            "COPY daily_product_stats (tenant_id, product_id, stat_date, units_sold, "
            "units_returned, revenue, avg_price, opening_on_hand, closing_on_hand, receipts_qty, "
            "availability_state, is_censored, promo_active, event_keys) FROM STDIN"
        ) as copy:
            days = [start + timedelta(days=i) for i in range(n_days)]
            for p, pid in enumerate(product_ids):
                for d in range(n_days):
                    units = int(sold_qty[p, d])
                    revenue = Decimal(int(sold_rev[p, d])).scaleb(-3)
                    avg = (
                        (revenue / (Decimal(units) / MILLI)).quantize(Decimal("0.0001"))
                        if units > 0
                        else None
                    )
                    copy.write_row(
                        (
                            self.tenant_id,
                            pid,
                            days[d],
                            _qty(units),
                            _qty(int(returned[p, d])),
                            revenue.quantize(Decimal("0.01")),
                            avg,
                            _qty(int(opening[p, d])),
                            _qty(int(closing[p, d])),
                            _qty(int(receipts[p, d])),
                            rules.STATE_NAMES[int(codes[p, d])],
                            bool(censored[p, d]),
                            bool(promo[p, d]),
                            events[d],
                        )
                    )
                    count += 1
        cursor.close()
        return count

    def _infer_intervals(self, end: date) -> int:
        """Replace the inferred stockout intervals with the runs found in the stats."""
        tid = self.tenant_id
        self.session.execute(
            text("DELETE FROM stockout_intervals WHERE tenant_id = :t AND source = 'inferred'"),
            {"t": tid},
        )
        result = self.session.execute(
            text(
                """
                INSERT INTO stockout_intervals
                    (tenant_id, product_id, start_date, end_date, source, note)
                SELECT tenant_id, product_id, MIN(stat_date),
                       CASE WHEN MAX(stat_date) >= :end THEN NULL ELSE MAX(stat_date) END,
                       'inferred', 'Inferred from the stock ledger'
                FROM (
                    SELECT tenant_id, product_id, stat_date,
                           stat_date - (ROW_NUMBER() OVER (
                               PARTITION BY product_id ORDER BY stat_date))::int AS grp
                    FROM daily_product_stats
                    WHERE tenant_id = :t AND availability_state = 'stocked_out_all_day'
                ) runs
                GROUP BY tenant_id, product_id, grp
                HAVING COUNT(*) >= :min_days
                """
            ),
            {"t": tid, "end": self._last_stat_date(end), "min_days": UNRECORDED_STOCKOUT_DAYS},
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def _last_stat_date(self, fallback: date) -> date:
        return self.last_rolled() or fallback
