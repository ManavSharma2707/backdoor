"""Reconciliation queries (`database.md` section 6). All three must return no rows.

Each query is scoped to one tenant with a bound parameter. They run in tests after every
scenario, in the data quality job, and on demand from `POST /inventory/reconcile`.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

BALANCE_MISMATCH_SQL = text(
    """
    WITH ledger AS (
        SELECT product_id, batch_id, SUM(quantity_delta) AS total
        FROM inventory_movements
        WHERE tenant_id = :tid
        GROUP BY product_id, batch_id
    )
    SELECT COALESCE(b.product_id, l.product_id) AS product_id,
           COALESCE(b.batch_id, l.batch_id) AS batch_id,
           COALESCE(b.on_hand, 0) AS on_hand,
           COALESCE(l.total, 0) AS ledger
    FROM stock_balances b
    FULL OUTER JOIN ledger l
      ON l.product_id = b.product_id AND l.batch_id IS NOT DISTINCT FROM b.batch_id
    WHERE (b.tenant_id = :tid OR b.tenant_id IS NULL)
      AND COALESCE(b.on_hand, 0) <> COALESCE(l.total, 0)
    ORDER BY 1, 2
    """
)

SALE_TOTAL_MISMATCH_SQL = text(
    """
    SELECT s.id, s.bill_no, s.total, s.subtotal, s.discount_total,
           COALESCE(SUM(l.line_total), 0) AS lines_total
    FROM sales s
    LEFT JOIN sale_lines l ON l.sale_id = s.id AND l.tenant_id = s.tenant_id
    WHERE s.tenant_id = :tid
    GROUP BY s.id, s.bill_no, s.total, s.subtotal, s.discount_total
    HAVING COALESCE(SUM(l.line_total), 0) <> s.total
        OR s.subtotal - s.discount_total <> s.total
    ORDER BY s.bill_no
    """
)

PO_RECEIVED_MISMATCH_SQL = text(
    """
    SELECT pl.id, pl.po_id, pl.product_id, pl.quantity_received,
           COALESCE(SUM(rl.quantity_received) FILTER (WHERE g.id IS NOT NULL), 0) AS receipts
    FROM purchase_order_lines pl
    LEFT JOIN receipt_lines rl ON rl.po_line_id = pl.id AND rl.tenant_id = pl.tenant_id
    LEFT JOIN goods_receipts g
      ON g.id = rl.receipt_id AND g.tenant_id = rl.tenant_id AND g.status = 'posted'
    WHERE pl.tenant_id = :tid
    GROUP BY pl.id, pl.po_id, pl.product_id, pl.quantity_received
    HAVING pl.quantity_received
        <> COALESCE(SUM(rl.quantity_received) FILTER (WHERE g.id IS NOT NULL), 0)
    ORDER BY pl.id
    """
)

RETURNED_QTY_MISMATCH_SQL = text(
    """
    SELECT l.id, l.sale_id, l.returned_qty, COALESCE(SUM(r.quantity), 0) AS returned_lines
    FROM sale_lines l
    LEFT JOIN sale_return_lines r ON r.sale_line_id = l.id AND r.tenant_id = l.tenant_id
    LEFT JOIN sale_returns h
      ON h.id = r.return_id AND h.tenant_id = r.tenant_id AND h.status = 'posted'
    WHERE l.tenant_id = :tid
    GROUP BY l.id, l.sale_id, l.returned_qty
    HAVING l.returned_qty <> COALESCE(SUM(r.quantity) FILTER (WHERE h.id IS NOT NULL), 0)
    ORDER BY l.id
    """
)


@dataclass(frozen=True)
class Mismatch:
    code: str
    entity_type: str
    entity_id: str
    detail: dict[str, Any]


def _text(value: Any) -> str:
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def find_mismatches(session: Session, tenant_id: uuid.UUID) -> list[Mismatch]:
    """Run every reconciliation query for one tenant. An empty list means the books agree."""
    found: list[Mismatch] = []
    params = {"tid": tenant_id}
    for row in session.execute(BALANCE_MISMATCH_SQL, params).mappings():
        found.append(
            Mismatch(
                code="BATCH_QTY_MISMATCH",
                entity_type="stock_balance",
                entity_id=f"{row['product_id']}:{row['batch_id'] or '-'}",
                detail={"on_hand": _text(row["on_hand"]), "ledger": _text(row["ledger"])},
            )
        )
    for row in session.execute(SALE_TOTAL_MISMATCH_SQL, params).mappings():
        found.append(
            Mismatch(
                code="SALE_TOTAL_MISMATCH",
                entity_type="sale",
                entity_id=str(row["id"]),
                detail={
                    "bill_no": row["bill_no"],
                    "total": _text(row["total"]),
                    "lines_total": _text(row["lines_total"]),
                },
            )
        )
    for row in session.execute(PO_RECEIVED_MISMATCH_SQL, params).mappings():
        found.append(
            Mismatch(
                code="PO_RECEIVED_MISMATCH",
                entity_type="purchase_order_line",
                entity_id=str(row["id"]),
                detail={
                    "quantity_received": _text(row["quantity_received"]),
                    "receipts": _text(row["receipts"]),
                },
            )
        )
    for row in session.execute(RETURNED_QTY_MISMATCH_SQL, params).mappings():
        found.append(
            Mismatch(
                code="RETURNED_QTY_MISMATCH",
                entity_type="sale_line",
                entity_id=str(row["id"]),
                detail={
                    "returned_qty": _text(row["returned_qty"]),
                    "return_lines": _text(row["returned_lines"]),
                },
            )
        )
    return found
