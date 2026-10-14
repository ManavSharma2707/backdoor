"""Collects the database backed data quality inputs and keeps `data_quality_issues` in step.

The checks themselves are pure (`app/engine/dq.py`). This service runs the queries they need,
and stores the findings: a finding that is still true keeps its row, a new one gets a row, and
an open row that was checked and is no longer true is marked resolved.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.engine import dq
from app.engine.constants import DUPLICATE_WINDOW_SECONDS, EXCEPTION_RECEIPT_DAYS
from app.engine.inputs import ProductInfo
from app.services.reconciliation import BALANCE_MISMATCH_SQL


def stock_findings(
    session: Session, tenant_id: uuid.UUID, labels: dict[uuid.UUID, str]
) -> list[dq.DqFinding]:
    """Negative balances and balances that differ from the ledger (current state only)."""
    negatives = [
        dq.StockIssue(r[0], r[1], float(r[2]))
        for r in session.execute(
            text(
                "SELECT product_id, batch_id, on_hand FROM stock_balances "
                "WHERE tenant_id = :t AND on_hand < 0"
            ),
            {"t": tenant_id},
        )
    ]
    mismatches = [
        dq.StockIssue(r[0], r[1], float(r[2]), float(r[3]))
        for r in session.execute(BALANCE_MISMATCH_SQL, {"tid": tenant_id})
    ]
    return dq.check_stock(negatives, mismatches, labels)


def purchasing_findings(
    session: Session,
    tenant_id: uuid.UUID,
    as_of: date,
    products: Sequence[ProductInfo],
    supplier_names: dict[uuid.UUID, str],
) -> list[dq.DqFinding]:
    """Late purchase orders (from the open lines already loaded) and exception receipts."""
    late: dict[uuid.UUID, dq.OverduePo] = {}
    for p in products:
        for line in p.incoming:
            if line.expected_date is not None and line.expected_date < as_of:
                late.setdefault(
                    line.po_id,
                    dq.OverduePo(
                        line.po_id,
                        line.po_number,
                        supplier_names.get(line.supplier_id, "the supplier"),
                        line.expected_date,
                        (as_of - line.expected_date).days,
                    ),
                )
    exceptions = [
        dq.ExceptionReceipts(r[0], r[1], int(r[2]))
        for r in session.execute(
            text(
                """
                SELECT g.supplier_id, s.name, COUNT(*)
                FROM goods_receipts g
                JOIN suppliers s ON s.tenant_id = g.tenant_id AND s.id = g.supplier_id
                WHERE g.tenant_id = :t AND g.is_exception AND g.status = 'posted'
                  AND g.received_on >= :since AND g.received_on < :as_of
                GROUP BY g.supplier_id, s.name ORDER BY s.name
                """
            ),
            {
                "t": tenant_id,
                "as_of": as_of,
                "since": as_of - timedelta(days=EXCEPTION_RECEIPT_DAYS),
            },
        )
    ]
    return dq.check_purchasing(sorted(late.values(), key=lambda o: o.po_number), exceptions)


def duplicate_findings(session: Session, tenant_id: uuid.UUID, as_of: date) -> list[dq.DqFinding]:
    rows = session.execute(
        text(
            """
            WITH basket AS (
                SELECT s.id, s.bill_no, s.sold_at, s.total,
                       string_agg(l.product_id::text || ':' || l.quantity::text, ',' ORDER BY
                                  l.product_id, l.quantity) AS sig
                FROM sales s
                JOIN sale_lines l ON l.tenant_id = s.tenant_id AND l.sale_id = s.id
                WHERE s.tenant_id = :t AND s.status = 'completed'
                  AND s.business_date >= :since AND s.business_date < :as_of
                GROUP BY s.id, s.bill_no, s.sold_at, s.total
            )
            SELECT a.id, a.bill_no, b.bill_no
            FROM basket a JOIN basket b
              ON a.sig = b.sig AND a.total = b.total AND a.id <> b.id AND a.sold_at > b.sold_at
             AND a.sold_at - b.sold_at <= make_interval(secs => :secs)
            ORDER BY a.bill_no
            """
        ),
        {
            "t": tenant_id,
            "as_of": as_of,
            "since": as_of - timedelta(days=30),
            "secs": DUPLICATE_WINDOW_SECONDS,
        },
    )
    return dq.check_duplicate_sales(dq.DuplicateBill(r[0], r[1], r[2]) for r in rows)


def unrecorded_stockout_findings(
    session: Session, tenant_id: uuid.UUID, as_of: date, labels: dict[uuid.UUID, str]
) -> list[dq.DqFinding]:
    rows = session.execute(
        text(
            """
            SELECT i.product_id, i.start_date, i.end_date,
                   EXISTS (
                       SELECT 1 FROM stockout_intervals r
                       WHERE r.tenant_id = i.tenant_id AND r.product_id = i.product_id
                         AND r.source = 'recorded' AND r.start_date <= COALESCE(i.end_date, :as_of)
                         AND COALESCE(r.end_date, :as_of) >= i.start_date) AS covered
            FROM stockout_intervals i
            WHERE i.tenant_id = :t AND i.source = 'inferred' AND i.start_date < :as_of
            """
        ),
        {"t": tenant_id, "as_of": as_of},
    )
    return dq.check_unrecorded_stockouts(
        (dq.InferredStockout(r[0], r[1], r[2], bool(r[3])) for r in rows), labels, as_of
    )


class DqStore:
    """Writes findings and resolves the ones that no longer apply."""

    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def save(
        self,
        findings: Iterable[dq.DqFinding],
        checked_codes: Iterable[str],
        run_id: uuid.UUID | None,
    ) -> dict[str, int]:
        """Upsert `findings`, and resolve open issues of `checked_codes` that were not found."""
        found = list(findings)
        keys = {(f.code, f.entity_type, f.entity_id) for f in found}
        open_rows = self.session.execute(
            text(
                "SELECT id, code, entity_type, entity_id FROM data_quality_issues "
                "WHERE tenant_id = :t AND resolved_at IS NULL"
            ),
            {"t": self.tenant_id},
        ).all()
        existing = {(r[1], r[2], r[3]): r[0] for r in open_rows}
        now = now_utc()
        inserted = updated = 0
        for f in found:
            params: dict[str, Any] = {
                "t": self.tenant_id,
                "run": run_id,
                "code": f.code,
                "sev": f.severity,
                "etype": f.entity_type,
                "eid": f.entity_id,
                "msg": f.message,
                "detail": _json({**f.detail, "label": f.entity_label}),
                "hint": f.fix_hint,
                "now": now,
            }
            row_id = existing.get((f.code, f.entity_type, f.entity_id))
            if row_id is None:
                self.session.execute(
                    text(
                        """
                        INSERT INTO data_quality_issues
                            (tenant_id, run_id, code, severity, entity_type, entity_id, message,
                             detail, fix_hint, detected_at)
                        VALUES (:t, :run, :code, :sev, :etype, :eid, :msg,
                                CAST(:detail AS jsonb), :hint, :now)
                        """
                    ),
                    params,
                )
                inserted += 1
            else:
                self.session.execute(
                    text(
                        """
                        UPDATE data_quality_issues
                        SET run_id = :run, severity = :sev, message = :msg,
                            detail = CAST(:detail AS jsonb), fix_hint = :hint
                        WHERE tenant_id = :t AND id = :id
                        """
                    ),
                    {**params, "id": row_id},
                )
                updated += 1
        checked = set(checked_codes)
        stale = [
            rid
            for (code, et, eid), rid in existing.items()
            if code in checked and (code, et, eid) not in keys
        ]
        if stale:
            self.session.execute(
                text(
                    "UPDATE data_quality_issues SET resolved_at = :now "
                    "WHERE tenant_id = :t AND id = ANY(:ids)"
                ),
                {"t": self.tenant_id, "ids": stale, "now": now},
            )
        return {"inserted": inserted, "updated": updated, "resolved": len(stale)}


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, default=str, sort_keys=True)
