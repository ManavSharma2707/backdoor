"""SQL fallback for the daily rollup (`engine-spec.md` section 3).

The real rollup service arrives in Prompt 4 (follow-up item P4.01 replaces this module). The rules
are the same: opening and closing stock from the ledger, availability state, censoring, promotion
and event flags. It is idempotent: it deletes the tenant rows first, then inserts the whole range.
"""

import re
import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

ROLLUP_TEXT = """
    INSERT INTO daily_product_stats
        (tenant_id, product_id, stat_date, units_sold, units_returned, revenue, avg_price,
         opening_on_hand, closing_on_hand, receipts_qty, availability_state, is_censored,
         promo_active, event_keys)
    WITH days AS (
        SELECT g::date AS stat_date
        FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') g
    ), prods AS (
        SELECT id AS product_id, category_id, launched_on
        FROM products WHERE tenant_id = :tid
    ), mv AS (
        SELECT product_id, business_date,
               SUM(quantity_delta) AS net,
               COALESCE(SUM(quantity_delta) FILTER (WHERE movement_type = 'receipt'), 0) AS rec
        FROM inventory_movements
        WHERE tenant_id = :tid AND business_date >= CAST(:start AS date)
        GROUP BY product_id, business_date
    ), pre AS (
        SELECT product_id, SUM(quantity_delta) AS qty
        FROM inventory_movements
        WHERE tenant_id = :tid AND business_date < CAST(:start AS date)
        GROUP BY product_id
    ), firsts AS (
        SELECT product_id, MIN(business_date) AS first_day
        FROM inventory_movements WHERE tenant_id = :tid GROUP BY product_id
    ), sl AS (
        SELECT l.product_id, l.business_date, SUM(l.quantity) AS units, SUM(l.line_total) AS revenue
        FROM sale_lines l
        JOIN sales s ON s.tenant_id = l.tenant_id AND s.id = l.sale_id
        WHERE l.tenant_id = :tid AND s.status = 'completed'
        GROUP BY l.product_id, l.business_date
    ), rt AS (
        SELECT rl.product_id, r.business_date, SUM(rl.quantity) AS units
        FROM sale_return_lines rl
        JOIN sale_returns r ON r.tenant_id = rl.tenant_id AND r.id = rl.return_id
        WHERE rl.tenant_id = :tid AND r.status = 'posted' AND rl.disposition = 'restock'
        GROUP BY rl.product_id, r.business_date
    ), grid AS (
        SELECT p.product_id, p.category_id, p.launched_on, d.stat_date,
               COALESCE(mv.net, 0) AS net, COALESCE(mv.rec, 0) AS rec,
               COALESCE(sl.units, 0) AS units, COALESCE(sl.revenue, 0) AS revenue,
               COALESCE(rt.units, 0) AS runits,
               COALESCE(pre.qty, 0) AS pre_qty, firsts.first_day AS first_day
        FROM prods p
        CROSS JOIN days d
        LEFT JOIN mv ON mv.product_id = p.product_id AND mv.business_date = d.stat_date
        LEFT JOIN sl ON sl.product_id = p.product_id AND sl.business_date = d.stat_date
        LEFT JOIN rt ON rt.product_id = p.product_id AND rt.business_date = d.stat_date
        LEFT JOIN pre ON pre.product_id = p.product_id
        LEFT JOIN firsts ON firsts.product_id = p.product_id
    ), run AS (
        SELECT grid.*,
               pre_qty + COALESCE(SUM(net) OVER (
                   PARTITION BY product_id ORDER BY stat_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS opening_q,
               pre_qty + SUM(net) OVER (PARTITION BY product_id ORDER BY stat_date) AS closing_q
        FROM grid
    ), covered AS (
        SELECT DISTINCT i.product_id AS cv_product, d.stat_date AS cv_date
        FROM stockout_intervals i
        JOIN days d ON d.stat_date BETWEEN i.start_date AND COALESCE(i.end_date, CAST(:end AS date))
        WHERE i.tenant_id = :tid AND i.source = 'recorded'
    ), state AS (
        SELECT run.*,
               CASE
                 WHEN launched_on IS NOT NULL AND stat_date < launched_on THEN 'not_launched'
                 WHEN first_day IS NULL OR first_day >= stat_date THEN 'unknown'
                 WHEN opening_q = 0 AND rec = 0 AND units = 0 THEN 'stocked_out_all_day'
                 WHEN opening_q = 0 AND rec = 0 THEN 'sold_out_during_day'
                 WHEN covered.cv_product IS NOT NULL
                      THEN CASE WHEN units > 0 THEN 'sold_out_during_day'
                                ELSE 'stocked_out_all_day' END
                 WHEN closing_q = 0 AND units > 0 THEN 'sold_out_during_day'
                 ELSE 'available'
               END AS availability
        FROM run
        LEFT JOIN covered ON covered.cv_product = run.product_id AND covered.cv_date = run.stat_date
    )
    SELECT :tid, product_id, stat_date, units, runits, revenue,
           CASE WHEN units > 0 THEN ROUND(revenue / units, 4) END,
           opening_q, closing_q, rec, availability,
           availability IN ('sold_out_during_day', 'stocked_out_all_day'),
           EXISTS (
               SELECT 1 FROM promotions pr
               WHERE pr.tenant_id = :tid AND state.stat_date BETWEEN pr.starts_on AND pr.ends_on
                 AND (pr.product_id = state.product_id OR pr.category_id = state.category_id)),
           COALESCE(ARRAY(
               SELECT DISTINCT ce.event_key FROM calendar_events ce
               WHERE ce.is_active
                 AND state.stat_date BETWEEN ce.start_date - ce.pre_window_days
                                         AND ce.end_date + ce.post_window_days
               ORDER BY 1), CAST('{}' AS text[]))
    FROM state
    """
ROLLUP_SQL = text(ROLLUP_TEXT)
ROLLUP_PSYCOPG = re.sub(r"(?<!:):(tid|start|end)\b", r"%(\1)s", ROLLUP_TEXT)


def rebuild_daily_stats(session: Session, tenant_id: uuid.UUID, start: date, end: date) -> int:
    """Delete and rebuild the tenant rows for the whole history range. Returns the row count."""
    session.execute(
        text("DELETE FROM daily_product_stats WHERE tenant_id = :tid"), {"tid": tenant_id}
    )
    session.execute(ROLLUP_SQL, {"tid": tenant_id, "start": start, "end": end})
    return int(
        session.execute(
            text("SELECT COUNT(*) FROM daily_product_stats WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).scalar_one()
    )
