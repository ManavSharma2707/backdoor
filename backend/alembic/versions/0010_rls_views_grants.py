"""rls views grants

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-13

Deny-all row level security on every table in `public`, no grants for the Supabase API roles,
and the two read views. The backend connects as the table owner, which bypasses RLS.
Tables created later (LangGraph checkpoints, `PostgresSaver.setup()`) need the same RLS step
after setup, see `app.jobs.run`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SET_RLS = """
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I {action} ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END
$$
"""

# The Supabase API roles do not exist on a plain local Postgres, so each step checks first.
REVOKE_API_ROLES = """
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE USAGE ON SCHEMA public FROM %I', r);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
        END IF;
    END LOOP;
END
$$
"""

V_PRODUCT_STOCK = """
CREATE VIEW v_product_stock WITH (security_invoker = true) AS
SELECT tenant_id, product_id,
       SUM(on_hand) AS on_hand,
       SUM(reserved_qty) AS reserved,
       SUM(on_hand * avg_unit_cost) AS stock_value
FROM stock_balances
GROUP BY tenant_id, product_id
"""

# Days to expiry are counted from the business date in Asia/Kolkata, not the server date.
V_BATCH_STOCK = """
CREATE VIEW v_batch_stock WITH (security_invoker = true) AS
SELECT b.tenant_id, b.id AS batch_id, b.product_id, b.batch_no, b.expiry_date,
       (b.expiry_date - (now() AT TIME ZONE 'Asia/Kolkata')::date) AS days_to_expiry,
       COALESCE(s.on_hand, 0) AS on_hand,
       b.unit_cost,
       COALESCE(s.on_hand, 0) * b.unit_cost AS value
FROM product_batches b
LEFT JOIN stock_balances s ON s.tenant_id = b.tenant_id AND s.batch_id = b.id
"""


def upgrade() -> None:
    op.execute(V_PRODUCT_STOCK)
    op.execute(V_BATCH_STOCK)
    op.execute(SET_RLS.format(action="ENABLE"))
    op.execute(REVOKE_API_ROLES)


def downgrade() -> None:
    op.execute(SET_RLS.format(action="DISABLE"))
    op.execute("DROP VIEW IF EXISTS v_batch_stock")
    op.execute("DROP VIEW IF EXISTS v_product_stock")
