"""Bulk loader: COPY the generated rows, rebuild balances from the ledger, run the rollup.

One transaction per tenant, so a failure leaves nothing half loaded. Rows go in dependency order
and every composite foreign key is satisfied because ids come from the same generator.
"""

import time
import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.services.rollup import RollupService
from seed.model import Catalog, cost4, make_uuid, tenant_uuid
from seed.schema import COLUMNS, LOAD_ORDER
from seed.sim import TenantData

log = get_logger(__name__)

# Tables with a tenant_id that the reset must never touch (the log survives demo resets).
ROLLUP_INPUTS = (
    "inventory_movements",
    "sale_lines",
    "sales",
    "sale_returns",
    "sale_return_lines",
    "products",
    "stockout_intervals",
    "promotions",
)
RESET_SKIP = frozenset({"audit_logs"})
# COPY writes explicit ids, which leaves identity sequences at 1. Without a reset the first bill
# saved through the API fails on a duplicate key.
IDENTITY_TABLES = (
    "sale_lines",
    "sale_return_lines",
    "inventory_movements",
    "forecast_values",
    "audit_logs",
    "agent_steps",
)


def sync_identity_sequences(cur: psycopg.Cursor[Any]) -> None:
    """Move every identity sequence past the largest id that was loaded."""
    for table in IDENTITY_TABLES:
        cur.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence({name}, 'id'), "
                "COALESCE(MAX(id), 1), COALESCE(MAX(id), 0) > 0) FROM {table}"
            ).format(name=sql.Literal(table), table=sql.Identifier(table))
        )


def psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def connect(database_url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(psycopg_url(database_url))


def copy_rows(cur: psycopg.Cursor[Any], table: str, rows: Iterable[Any]) -> int:
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS[table])
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), columns)
    count = 0
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def reset_order(cur: psycopg.Cursor[Any]) -> list[str]:
    """Tenant owned tables, children before parents, from the foreign keys in the database."""
    cur.execute(
        """
        SELECT c.table_name FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'
          AND t.table_type = 'BASE TABLE'
        """
    )
    tables = {r[0] for r in cur.fetchall()} - RESET_SKIP
    cur.execute(
        """
        SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
        FROM pg_constraint c WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
        """
    )
    children: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in cur.fetchall():
        child, parent = child.strip('"'), parent.strip('"')
        if child in tables and parent in tables and child != parent:
            children[parent].add(child)
    order: list[str] = []
    seen: set[str] = set()

    def visit(table: str) -> None:
        if table in seen:
            return
        seen.add(table)
        for child in sorted(children[table]):
            visit(child)
        order.append(table)

    for table in sorted(tables):
        visit(table)
    return order


def reset_tenants(conn: psycopg.Connection[Any], tenant_ids: list[uuid.UUID]) -> None:
    with conn.cursor() as cur:
        order = reset_order(cur)
        for tid in tenant_ids:
            for table in order:
                cur.execute(
                    sql.SQL("DELETE FROM {} WHERE tenant_id = %s").format(sql.Identifier(table)),
                    (tid,),
                )
            cur.execute("DELETE FROM tenants WHERE id = %s", (tid,))
    conn.commit()


def tax_rate_ids(cur: psycopg.Cursor[Any]) -> dict[str, uuid.UUID]:
    cur.execute("SELECT code, id FROM tax_rates")
    found = dict(cur.fetchall())
    if len(found) < 4:
        raise RuntimeError("Tax rates are missing. Run `python -m app.jobs.run migrate` first.")
    return found


def load_tenant(
    conn: psycopg.Connection[Any],
    catalog: Catalog,
    static: dict[str, list[Any]],
    data: TenantData,
    true_demand: Iterable[Any],
    tenant_row: tuple[Any, ...],
    user_rows: list[tuple[Any, ...]],
    settings_row: tuple[Any, ...],
    start: date,
    end: date,
    database_url: str,
) -> dict[str, float]:
    profile = catalog.profile
    tid = tenant_uuid(profile)
    timings: dict[str, float] = {}
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("SET LOCAL synchronous_commit = off")
        copy_rows(cur, "tenants", [tenant_row])
        copy_rows(cur, "users", user_rows)
        copy_rows(cur, "business_settings", [settings_row])
        for table in LOAD_ORDER:
            if table == "synthetic_true_demand":
                rows: Iterable[Any] = true_demand
            elif table in static:
                rows = static[table]
            else:
                rows = data.rows[table]
            n = copy_rows(cur, table, rows)
            log.info("seed.copied", tenant=profile.key, table=table, rows=n)
        sync_identity_sequences(cur)
        timings["copy"] = time.time() - t0
        t1 = time.time()
        rebuild_balances(cur, tid, data, catalog)
        timings["balances"] = time.time() - t1
        t2 = time.time()
        # Fresh tables have no statistics, and without them the rollup picks a plan that runs for minutes.
        for table in ROLLUP_INPUTS:
            cur.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
    conn.commit()
    run_rollup(database_url, tid, start, end)
    timings["rollup"] = time.time() - t2
    with conn.cursor() as cur:
        conn.autocommit = True
        for table in (
            "inventory_movements",
            "sale_lines",
            "sales",
            "daily_product_stats",
            "synthetic_true_demand",
        ):
            cur.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
        conn.autocommit = False
    timings["total"] = time.time() - t0
    return timings


def run_rollup(database_url: str, tid: uuid.UUID, start: date, end: date) -> int:
    """Run the rollup service on its own connection, after the tenant rows are committed."""
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            rows = RollupService(session, tid).rebuild(start, end).rows
            session.commit()
    finally:
        engine.dispose()
    return rows


def rebuild_balances(
    cur: psycopg.Cursor[Any], tid: uuid.UUID, data: TenantData, catalog: Catalog
) -> None:
    """stock_balances from the ledger. Average cost comes from the simulation's cost tracking."""
    cur.execute(
        "CREATE TEMP TABLE _seed_avg (product_id uuid, batch_id uuid, avg_cost numeric(12,4)) ON COMMIT DROP"
    )
    ti = catalog.profile.index
    rows = []
    for (p, b), (_qty, avg4, _when) in data.final_balances.items():
        rows.append(
            (
                make_uuid(ti, 4, p + 1),
                make_uuid(ti, 9, b + 1) if b is not None else None,
                cost4(avg4),
            )
        )
    with cur.copy("COPY _seed_avg (product_id, batch_id, avg_cost) FROM STDIN") as copy:
        for r in rows:
            copy.write_row(r)
    cur.execute(
        """
        INSERT INTO stock_balances
            (tenant_id, product_id, batch_id, on_hand, reserved_qty, avg_unit_cost, last_movement_at)
        SELECT m.tenant_id, m.product_id, m.batch_id, SUM(m.quantity_delta), 0,
               COALESCE(MAX(a.avg_cost), 0), MAX(m.occurred_at)
        FROM inventory_movements m
        LEFT JOIN _seed_avg a
          ON a.product_id = m.product_id AND a.batch_id IS NOT DISTINCT FROM m.batch_id
        WHERE m.tenant_id = %s
        GROUP BY m.tenant_id, m.product_id, m.batch_id
        """,
        (tid,),
    )


BIG_TABLES = (
    "inventory_movements",
    "sale_lines",
    "sales",
    "daily_product_stats",
    "synthetic_true_demand",
    "purchase_order_lines",
    "product_batches",
    "receipt_lines",
    "stock_balances",
)


def compact(database_url: str) -> None:
    """VACUUM FULL the large tables after a reset, so deleted rows do not keep using space."""
    with psycopg.connect(psycopg_url(database_url), autocommit=True) as conn, conn.cursor() as cur:
        for table in BIG_TABLES:
            cur.execute(sql.SQL("VACUUM (FULL, ANALYZE) {}").format(sql.Identifier(table)))
