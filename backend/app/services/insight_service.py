"""Dashboard and insight queries (`api-spec.md` section 9).

Everything here reads stored records: the current plan, backtests, effects, the ledger and the
purchase orders. No number is computed from a language model and nothing is written.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.timeutil import week_start
from app.engine.deadstock import abc_classes
from app.services.common import not_found

PAISA = Decimal("0.01")


def money(value: Any) -> str:
    return str(Decimal(value or 0).quantize(PAISA))


def qty(value: Any) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.001")))


class InsightService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.tid = ctx.tenant_id

    def _rows(self, sql: str, **params: Any) -> list[Any]:
        return list(self.session.execute(text(sql), {"t": self.tid, **params}).all())

    def _current_report(self) -> Any:
        rows = self._rows(
            """
            SELECT id, week_start, version, generated_at, status, recommendation_run_id, summary
            FROM weekly_reports
            WHERE tenant_id = :t AND is_current AND status = 'ready'
            ORDER BY week_start DESC LIMIT 1
            """
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------ dashboard

    def dashboard_summary(self) -> dict[str, Any]:
        report = self._current_report()
        stock_value = self._rows(
            "SELECT COALESCE(SUM(on_hand * avg_unit_cost), 0) FROM stock_balances WHERE tenant_id = :t"
        )[0][0]
        dq = {
            r[0]: int(r[1])
            for r in self._rows(
                """
                SELECT severity, COUNT(*) FROM data_quality_issues
                WHERE tenant_id = :t AND resolved_at IS NULL GROUP BY severity
                """
            )
        }
        out: dict[str, Any] = {
            "plan": None,
            "kpis": {
                "stock_value": money(stock_value),
                "suggested_spend": None,
                "budget": None,
                "critical_lines": 0,
                "non_moving_value": money(0),
                "near_expiry_value": money(0),
                "expired_value": money(0),
                "data_warnings": dq.get("warning", 0),
                "data_errors": dq.get("error", 0),
            },
            "needs_attention": [],
            "data_quality": {
                "error": dq.get("error", 0),
                "warning": dq.get("warning", 0),
                "info": dq.get("info", 0),
            },
        }
        if report is None:
            return out
        summary = report.summary
        out["plan"] = {
            "id": str(report.id),
            "week_start": report.week_start.isoformat(),
            "version": report.version,
            "generated_at": report.generated_at.isoformat(),
            "festival_note": summary.get("festival_note"),
        }
        out["kpis"].update(
            suggested_spend=summary.get("planned_spend"),
            budget=summary.get("budget"),
            needed_spend=summary.get("needed_spend"),
            critical_lines=summary.get("critical_count", 0),
            non_moving_value=summary.get("non_moving_value", money(0)),
            near_expiry_value=summary.get("expiry_exposure_value", money(0)),
            expired_value=summary.get("expired_value", money(0)),
        )
        rows = self._rows(
            """
            SELECT l.id, p.sku, p.name, l.risk_level, l.warnings, l.reason_codes,
                   l.projected_stockout_date, l.stockout_probability
            FROM recommendation_lines l
            JOIN products p ON p.tenant_id = l.tenant_id AND p.id = l.product_id
            WHERE l.tenant_id = :t AND l.run_id = :run
              AND (l.risk_level IN ('critical', 'high') OR 'PO_OVERDUE' = ANY(l.warnings))
            ORDER BY CASE l.risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                     l.stockout_probability DESC, p.name
            LIMIT 8
            """,
            run=report.recommendation_run_id,
        )
        for r in rows:
            out["needs_attention"].append(
                {
                    "line_id": str(r[0]),
                    "report_id": str(report.id),
                    "sku": r[1],
                    "name": r[2],
                    "risk_level": r[3],
                    "headline": _headline(r[3], r[4], r[5]),
                    "projected_stockout_date": r[6].isoformat() if r[6] else None,
                }
            )
        return out

    def trends(self, weeks: int) -> dict[str, Any]:
        last_full = week_start(today_ist()) - timedelta(days=1)
        end = last_full if self._current_report() is None else max(last_full, self._max_stat_date())
        end = min(end, self._max_stat_date())
        start = week_start(end) - timedelta(weeks=weeks - 1)
        rows = self._rows(
            """
            SELECT date_trunc('week', stat_date)::date AS wk, SUM(revenue), SUM(units_sold - units_returned)
            FROM daily_product_stats
            WHERE tenant_id = :t AND stat_date >= :s AND stat_date <= :e
            GROUP BY 1 ORDER BY 1
            """,
            s=start,
            e=end,
        )
        events = self._rows(
            """
            SELECT event_key, name, start_date, end_date, kind FROM calendar_events
            WHERE is_active AND kind = 'festival' AND end_date >= :s AND start_date <= :e
            ORDER BY start_date
            """,
            s=start,
            e=end,
        )
        return {
            "weeks": [
                {"week_start": r[0].isoformat(), "revenue": money(r[1]), "units": qty(r[2])}
                for r in rows
            ],
            "festival_bands": [
                {
                    "event_key": e[0],
                    "name": e[1],
                    "start": e[2].isoformat(),
                    "end": e[3].isoformat(),
                }
                for e in events
            ],
        }

    def _max_stat_date(self) -> date:
        value = self._rows("SELECT MAX(stat_date) FROM daily_product_stats WHERE tenant_id = :t")[
            0
        ][0]
        return value or today_ist()

    def cover_by_category(self) -> dict[str, Any]:
        report = self._current_report()
        if report is None:
            return {"plan_id": None, "categories": []}
        rows = self._rows(
            """
            SELECT c.id, c.name, SUM(l.on_hand_usable), SUM(l.avg_daily_forecast),
                   COUNT(*) FILTER (WHERE l.risk_level = 'critical'),
                   COUNT(*) FILTER (WHERE l.risk_level = 'high'), COUNT(*)
            FROM recommendation_lines l
            JOIN products p ON p.tenant_id = l.tenant_id AND p.id = l.product_id
            JOIN categories c ON c.tenant_id = p.tenant_id AND c.id = p.category_id
            WHERE l.tenant_id = :t AND l.run_id = :run
            GROUP BY c.id, c.name ORDER BY c.name
            """,
            run=report.recommendation_run_id,
        )
        return {
            "plan_id": str(report.id),
            "categories": [
                {
                    "category_id": str(r[0]),
                    "category": r[1],
                    "usable_stock": qty(r[2]),
                    "daily_demand": qty(r[3]),
                    "days_of_cover": None
                    if not r[3] or r[3] <= 0
                    else round(float(r[2] / r[3]), 1),
                    "critical_lines": int(r[4]),
                    "high_lines": int(r[5]),
                    "lines": int(r[6]),
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------------ insights

    def movers(self, window: int) -> dict[str, Any]:
        end = self._max_stat_date()
        start = end - timedelta(days=window - 1)
        rows = self._rows(
            """
            SELECT d.product_id, p.sku, p.name, SUM(d.revenue), SUM(d.units_sold - d.units_returned)
            FROM daily_product_stats d
            JOIN products p ON p.tenant_id = d.tenant_id AND p.id = d.product_id
            WHERE d.tenant_id = :t AND d.stat_date BETWEEN :s AND :e AND p.is_active
            GROUP BY d.product_id, p.sku, p.name
            """,
            s=start,
            e=end,
        )
        revenue = {r[0]: float(r[3]) for r in rows}
        abc = abc_classes(revenue)
        total = sum(v for v in revenue.values() if v > 0) or 1.0
        items = [
            {
                "product_id": str(r[0]),
                "sku": r[1],
                "name": r[2],
                "revenue": money(r[3]),
                "units": qty(r[4]),
                "abc": abc[r[0]],
                "revenue_share": round(float(r[3]) / total, 4),
                "units_per_day": round(float(r[4]) / window, 2),
            }
            for r in rows
        ]
        items.sort(key=lambda i: -float(i["revenue"]))
        report = self._current_report()
        slow: list[dict[str, Any]] = []
        not_moving: list[dict[str, Any]] = []
        if report is not None:
            for r in self._rows(
                """
                SELECT l.id, p.sku, p.name, l.stock_status, l.days_of_cover, l.excess_value,
                       l.on_hand_usable, l.unit_cost
                FROM recommendation_lines l
                JOIN products p ON p.tenant_id = l.tenant_id AND p.id = l.product_id
                WHERE l.tenant_id = :t AND l.run_id = :run
                  AND l.stock_status IN ('slow', 'non_moving', 'unverified')
                ORDER BY l.on_hand_usable * COALESCE(l.unit_cost, 0) DESC
                """,
                run=report.recommendation_run_id,
            ):
                row = {
                    "line_id": str(r[0]),
                    "sku": r[1],
                    "name": r[2],
                    "status": r[3],
                    "days_of_cover": None if r[4] is None else float(r[4]),
                    "stock_value": money((r[6] or 0) * (r[7] or 0)),
                }
                (slow if r[3] == "slow" else not_moving).append(row)
        return {
            "window_days": window,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "counts": {k: sum(1 for i in items if i["abc"] == k) for k in "ABC"},
            "fast": sorted(items, key=lambda i: -float(i["units_per_day"]))[:10],
            "top_revenue": items[:10],
            "slow": slow,
            "non_moving": not_moving,
        }

    def forecast_accuracy(self, segment: str | None) -> dict[str, Any]:
        runs = self._rows(
            """
            SELECT id, as_of_date, profile FROM forecast_runs
            WHERE tenant_id = :t AND kind = 'backtest' AND status = 'succeeded'
            ORDER BY as_of_date DESC, started_at DESC LIMIT 1
            """
        )
        if not runs:
            return {"run": None, "tenant": None, "segments": []}
        run = runs[0]
        rows = self._rows(
            """
            SELECT scope, scope_key, method, n_points, mae, wape, bias, rmse, coverage_ratio,
                   is_selected, notes
            FROM forecast_backtests WHERE tenant_id = :t AND run_id = :run
            """,
            run=run[0],
        )

        def metric(r: Any) -> dict[str, Any]:
            return {
                "mae": float(r[4]),
                "wape": None if r[5] is None else float(r[5]),
                "bias": None if r[6] is None else float(r[6]),
                "rmse": float(r[7]),
                "points": int(r[3]),
                "coverage": float(r[8]),
            }

        tenant: dict[str, Any] = {}
        for r in rows:
            if r[0] == "tenant" and r[1] == "overall":
                tenant[f"{r[2]}:{(r[10] or {}).get('scope', 'all')}"] = metric(r)
        by_segment: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r[0] != "segment":
                continue
            seg = by_segment.setdefault(
                r[1], {"segment": r[1], "demand_class": r[1].split("|")[1], "methods": {}}
            )
            seg["methods"][r[2]] = metric(r)
            if r[9]:
                seg["selected"] = r[2]
                seg["reason"] = (r[10] or {}).get("reason")
                seg["products"] = (r[10] or {}).get("n_products")
                seg["valid"] = (r[10] or {}).get("valid")
        segments = []
        for seg in by_segment.values():
            if segment and segment.lower() not in seg["segment"].lower():
                continue
            chosen = seg["methods"].get(seg.get("selected", ""))
            base = seg["methods"].get("moving_average_28")
            if chosen is None or not seg.get("valid"):
                continue
            seg["wape_note"] = (
                "WAPE is not meaningful for this demand type"
                if seg["demand_class"] in ("intermittent", "lumpy")
                else None
            )
            if seg["wape_note"]:
                chosen = {**chosen, "wape": None}
            seg["selected_metrics"] = chosen
            seg["baseline_metrics"] = base
            seg["improvement_vs_baseline"] = (
                None
                if not base or base["mae"] == 0
                else round((base["mae"] - chosen["mae"]) / base["mae"], 4)
            )
            segments.append(seg)
        segments.sort(key=lambda s: s["segment"])
        return {
            "run": {"id": str(run[0]), "as_of": run[1].isoformat(), "profile": run[2]},
            "tenant": {
                "selected": tenant.get("selected:wape"),
                "baseline": tenant.get("moving_average_28:wape"),
                "seasonal_naive": tenant.get("seasonal_naive:wape"),
                "selected_all": tenant.get("selected:all"),
            },
            "segments": segments,
        }

    def forecast_vs_actual(
        self, product_id: uuid.UUID | None, category_id: uuid.UUID | None, weeks: int
    ) -> dict[str, Any]:
        end = week_start(self._max_stat_date()) - timedelta(days=1)
        start = week_start(end) - timedelta(weeks=weeks - 1)
        where_p, params = "", {"s": start, "e": end}
        if product_id:
            where_p, params["p"] = "AND d.product_id = :p", product_id
        elif category_id:
            where_p, params["c"] = (
                "AND d.product_id IN (SELECT id FROM products WHERE tenant_id = :t AND category_id = :c)",
                category_id,
            )
        actual = {
            r[0]: float(r[1])
            for r in self._rows(
                f"""
                SELECT date_trunc('week', d.stat_date)::date, SUM(d.units_sold - d.units_returned)
                FROM daily_product_stats d
                WHERE d.tenant_id = :t AND d.stat_date BETWEEN :s AND :e {where_p}
                GROUP BY 1
                """,
                **params,
            )
        }
        f_where = where_p.replace("d.product_id", "v.product_id")
        forecast = {
            r[0]: (float(r[1]), float(r[2]), float(r[3]))
            for r in self._rows(
                f"""
                SELECT r.as_of_date, SUM(v.yhat), SUM(v.yhat_lower), SUM(v.yhat_upper)
                FROM forecast_runs r
                JOIN forecast_values v ON v.tenant_id = r.tenant_id AND v.run_id = r.id
                WHERE r.tenant_id = :t AND r.kind = 'weekly' AND r.status = 'succeeded'
                  AND r.as_of_date BETWEEN :s AND :e
                  AND v.forecast_date >= r.as_of_date AND v.forecast_date < r.as_of_date + 7 {f_where}
                GROUP BY r.as_of_date
                """,
                **params,
            )
        }
        series = []
        wk = start
        while wk <= week_start(end):
            f = forecast.get(wk)
            series.append(
                {
                    "week_start": wk.isoformat(),
                    "actual": round(actual.get(wk, 0.0), 3),
                    "forecast": None if f is None else round(f[0], 3),
                    "lower": None if f is None else round(f[1], 3),
                    "upper": None if f is None else round(f[2], 3),
                }
            )
            wk += timedelta(days=7)
        return {
            "series": series,
            "note": "Each forecast is the one made on the Monday of that week.",
        }

    def festival_effects(self) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT e.event_key, c.name, e.window, e.multiplier, e.origin, e.n_occurrences,
                   e.n_products, e.consistency, e.confidence, e.is_applied, e.evidence, e.computed_at
            FROM event_category_effects e
            JOIN categories c ON c.tenant_id = e.tenant_id AND c.id = e.category_id
            WHERE e.tenant_id = :t
            ORDER BY e.event_key, c.name, e.window
            """
        )
        names = {
            r[0]: (r[1], r[2], r[3])
            for r in self._rows(
                """
                SELECT DISTINCT ON (event_key) event_key, name, kind, is_verified
                FROM calendar_events WHERE is_active
                ORDER BY event_key, (end_date < :today), ABS(start_date - :today)
                """,
                today=today_ist(),
            )
        }
        events: dict[str, dict[str, Any]] = {}
        for r in rows:
            meta = names.get(r[0], (r[0], "festival", True))
            ev = events.setdefault(
                r[0],
                {
                    "event_key": r[0],
                    "name": meta[0],
                    "kind": meta[1],
                    "dates_may_shift": not meta[2],
                    "categories": [],
                },
            )
            if not r[9] and abs(float(r[3]) - 1.0) < 0.05 and not (r[10] or {}).get("occurrences"):
                continue
            ev["categories"].append(
                {
                    "category": r[1],
                    "window": r[2],
                    "multiplier": float(r[3]),
                    "origin": r[4],
                    "n_occurrences": int(r[5]),
                    "n_products": int(r[6]),
                    "consistency": None if r[7] is None else float(r[7]),
                    "confidence": r[8],
                    "applied": bool(r[9]),
                    "label": "Set by you"
                    if (r[4] == "configured" and r[9])
                    else (
                        "Learned from past years"
                        if r[9]
                        else "Not enough evidence to adjust forecast"
                    ),
                    "evidence": r[10] or {},
                    "computed_at": r[11].isoformat(),
                }
            )
        return {"events": list(events.values())}

    def expiry_waste(self, months: int) -> dict[str, Any]:
        end = today_ist()
        start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
        rows = self._rows(
            """
            SELECT date_trunc('month', m.business_date)::date, m.movement_type,
                   SUM(-m.quantity_delta),
                   SUM(-m.quantity_delta * COALESCE(m.unit_cost, b.avg_unit_cost, 0))
            FROM inventory_movements m
            LEFT JOIN (SELECT product_id, MAX(avg_unit_cost) AS avg_unit_cost FROM stock_balances
                       WHERE tenant_id = :t GROUP BY product_id) b ON b.product_id = m.product_id
            WHERE m.tenant_id = :t AND m.business_date >= :s
              AND m.movement_type IN ('expiry_writeoff', 'damage', 'supplier_return')
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            s=start,
        )
        by_reason: dict[str, dict[str, Decimal]] = {}
        by_month: dict[str, dict[str, Any]] = {}
        for month, kind, q, value in rows:
            slot = by_reason.setdefault(kind, {"qty": Decimal(0), "value": Decimal(0)})
            slot["qty"] += Decimal(q or 0)
            slot["value"] += Decimal(value or 0)
            m = by_month.setdefault(month.isoformat(), {"month": month.isoformat()})
            m[kind] = money(value)
        total_lost = sum(
            (v["value"] for k, v in by_reason.items() if k != "supplier_return"), Decimal(0)
        )
        return {
            "months": months,
            "since": start.isoformat(),
            "by_reason": [
                {"reason": k, "qty": qty(v["qty"]), "value": money(v["value"])}
                for k, v in sorted(by_reason.items())
            ],
            "by_month": list(by_month.values()),
            "total_written_off_value": money(total_lost),
            "returned_to_suppliers_value": money(
                by_reason.get("supplier_return", {}).get("value", 0)
            ),
        }

    # ------------------------------------------------------------------ suppliers

    def supplier_scorecards(self, supplier_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        extra = "AND s.id = :sid" if supplier_id else ""
        params: dict[str, Any] = {"sid": supplier_id} if supplier_id else {}
        suppliers = self._rows(
            f"""
            SELECT s.id, s.code, s.name FROM suppliers s
            WHERE s.tenant_id = :t {extra} ORDER BY s.name
            """,
            **params,
        )
        if supplier_id and not suppliers:
            raise not_found("supplier")
        delays = {
            r[0]: r
            for r in self._rows(
                """
                WITH first_receipt AS (
                    SELECT po.id, po.supplier_id, po.expected_date, MIN(g.received_on) AS first_on
                    FROM purchase_orders po
                    JOIN goods_receipts g ON g.tenant_id = po.tenant_id AND g.purchase_order_id = po.id
                         AND g.status = 'posted'
                    WHERE po.tenant_id = :t AND po.expected_date IS NOT NULL
                    GROUP BY po.id, po.supplier_id, po.expected_date
                )
                SELECT supplier_id, COUNT(*),
                       COUNT(*) FILTER (WHERE first_on > expected_date),
                       AVG(GREATEST(first_on - expected_date, 0)) FILTER (WHERE first_on > expected_date)
                FROM first_receipt GROUP BY supplier_id
                """
            )
        }
        fills = {
            r[0]: r
            for r in self._rows(
                """
                SELECT po.supplier_id, SUM(pl.quantity_ordered), SUM(pl.quantity_received), COUNT(DISTINCT po.id)
                FROM purchase_orders po
                JOIN purchase_order_lines pl ON pl.tenant_id = po.tenant_id AND pl.po_id = po.id
                WHERE po.tenant_id = :t AND po.status IN ('received', 'closed', 'partially_received')
                GROUP BY po.supplier_id
                """
            )
        }
        drift = {
            r[0]: r[1]
            for r in self._rows(
                """
                WITH ranked AS (
                    SELECT supplier_id, product_id, purchase_price, effective_from,
                           FIRST_VALUE(purchase_price) OVER w AS first_price,
                           FIRST_VALUE(purchase_price) OVER (PARTITION BY supplier_id, product_id
                               ORDER BY effective_from DESC) AS last_price,
                           COUNT(*) OVER (PARTITION BY supplier_id, product_id) AS n
                    FROM supplier_product_terms
                    WHERE tenant_id = :t AND effective_from >= CURRENT_DATE - 365
                    WINDOW w AS (PARTITION BY supplier_id, product_id ORDER BY effective_from)
                )
                SELECT supplier_id,
                       AVG((last_price - first_price) / NULLIF(first_price, 0)) FILTER (WHERE n >= 2)
                FROM (SELECT DISTINCT supplier_id, product_id, first_price, last_price, n FROM ranked) x
                GROUP BY supplier_id
                """
            )
        }
        overdue = {
            r[0]: int(r[1])
            for r in self._rows(
                """
                SELECT supplier_id, COUNT(*) FROM purchase_orders
                WHERE tenant_id = :t AND status IN ('sent', 'partially_received')
                  AND expected_date < :today GROUP BY supplier_id
                """,
                today=today_ist(),
            )
        }
        report = self._current_report()
        friction: dict[uuid.UUID, float] = {}
        if report is not None:
            friction = {
                r[0]: float(r[1])
                for r in self._rows(
                    """
                    SELECT supplier_id, AVG(pack_excess_qty / NULLIF(suggested_qty, 0))
                    FROM recommendation_lines
                    WHERE tenant_id = :t AND run_id = :run AND suggested_qty > 0 AND supplier_id IS NOT NULL
                    GROUP BY supplier_id
                    """,
                    run=report.recommendation_run_id,
                )
                if r[1] is not None
            }
        out = []
        for sid, code, name in suppliers:
            d, f = delays.get(sid), fills.get(sid)
            out.append(
                {
                    "supplier_id": str(sid),
                    "code": code,
                    "name": name,
                    "orders_checked": int(d[1]) if d else 0,
                    "delay_rate": None if not d or not d[1] else round(int(d[2]) / int(d[1]), 3),
                    "avg_delay_days": None if not d or d[3] is None else round(float(d[3]), 1),
                    "fill_rate": None if not f or not f[1] else round(float(f[2] / f[1]), 3),
                    "price_drift": None if drift.get(sid) is None else round(float(drift[sid]), 4),
                    "pack_friction": None if sid not in friction else round(friction[sid], 3),
                    "overdue_orders": overdue.get(sid, 0),
                }
            )
        return out

    # ------------------------------------------------------------------ data quality

    def issues(
        self, resolved: bool, page_size: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        cond = "resolved_at IS NOT NULL" if resolved else "resolved_at IS NULL"
        total = self._rows(
            f"SELECT COUNT(*) FROM data_quality_issues WHERE tenant_id = :t AND {cond}"
        )[0][0]
        rows = self._rows(
            f"""
            SELECT id, code, severity, entity_type, entity_id, message, detail, fix_hint, detected_at,
                   resolved_at
            FROM data_quality_issues WHERE tenant_id = :t AND {cond}
            ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, code, detected_at DESC
            LIMIT :n OFFSET :o
            """,
            n=page_size,
            o=offset,
        )
        return [
            {
                "id": str(r[0]),
                "code": r[1],
                "severity": r[2],
                "entity_type": r[3],
                "entity_id": None if r[4] is None else str(r[4]),
                "message": r[5],
                "label": (r[6] or {}).get("label"),
                "fix_hint": r[7],
                "detected_at": r[8].isoformat(),
                "resolved_at": None if r[9] is None else r[9].isoformat(),
            }
            for r in rows
        ], int(total)


def _headline(risk: str, warnings: list[str], reasons: list[str]) -> str:
    if "OUT_OF_STOCK_NOW" in reasons:
        return "Out of stock now"
    if "PO_OVERDUE" in warnings:
        return "An order is late"
    return "Likely to run out soon" if risk == "critical" else "Could run out before delivery"


def require_current(service: InsightService) -> Any:
    report = service._current_report()
    if report is None:
        raise AppError(ErrorCode.NOT_FOUND, "There is no plan yet.")
    return report
