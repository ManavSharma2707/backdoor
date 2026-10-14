"""Seed the demo tenants: `python -m seed.run --tenants all [--scale 1.0] [--reset]`.

Generation is deterministic and runs in memory first, then each tenant is bulk loaded in one
transaction. `--reset` removes the chosen tenants (and only them) before loading.
"""

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.jobs.reference_data import upsert_reference_data
from app.services.reconciliation import find_mismatches
from seed import accounts, loader, static_rows
from seed.corpus.generator import app_docs, build_corpus, document_rows
from seed.generate import Generated, generate_tenant
from seed.model import load_catalog, tenant_uuid
from seed.profiles import (
    DEFAULT_BASE_SEED,
    DEFAULT_END_DATE,
    PROFILES,
    SCENARIOS_PATH,
    Profile,
    history_start,
    resolve_tenants,
)
from seed.scenarios import plan_scenarios, write_scenarios_yaml

log = get_logger(__name__)


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m seed.run", description="Load the demo tenants")
    parser.add_argument("--tenants", default="all", help="all or a list such as fmcg_a,med_a")
    parser.add_argument("--scale", type=float, default=1.0, help="volume factor, 1.0 is full")
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END_DATE)
    parser.add_argument("--seed", type=int, default=None, help="base seed (default from env)")
    parser.add_argument("--reset", action="store_true", help="remove the chosen tenants first")
    parser.add_argument("--no-knowledge", action="store_true", help="skip the knowledge corpus")
    parser.add_argument("--no-backfill", action="store_true", help="accepted, backfill is Prompt 4")
    return parser


def write_scenarios_file(end_date: date, base_seed: int) -> None:
    plans = [plan_scenarios(load_catalog(p), end_date, base_seed) for p in PROFILES.values()]
    write_scenarios_yaml(plans, end_date, SCENARIOS_PATH)


def load_generated(
    conn: object,
    gen: Generated,
    password_hash: str,
    tax_ids: dict[str, object],
    budget_scale: float,
    end_date: date,
    knowledge: bool,
    base_seed: int,
) -> dict[str, float]:
    catalog = gen.catalog
    static = {
        "categories": static_rows.category_rows(catalog),
        "products": static_rows.product_rows(catalog, tax_ids),
        "product_prices": static_rows.price_rows(catalog, gen.timelines, gen.plan),
        "suppliers": static_rows.supplier_rows(catalog),
        "supplier_product_terms": static_rows.term_rows(catalog, gen.timelines, gen.plan),
        "promotions": static_rows.promotion_rows(catalog, gen.timelines, gen.plan),
    }
    budget = accounts.weekly_budget(gen.data, gen.plan.budget_factor, budget_scale)
    timings = loader.load_tenant(
        conn,  # type: ignore[arg-type]
        catalog,
        static,
        gen.data,
        static_rows.true_demand_rows(catalog, gen.demand),
        static_rows.tenant_row(catalog),
        [accounts.owner_row(catalog, password_hash)],
        accounts.settings_row(catalog, budget),
        history_start(end_date),
        end_date,
    )
    if knowledge:
        docs = build_corpus(catalog, base_seed)
        doc_rows, chunk_rows = document_rows(docs, catalog, static_rows.CREATED)
        with conn.cursor() as cur:  # type: ignore[attr-defined]
            loader.copy_rows(cur, "knowledge_documents", doc_rows)
            loader.copy_rows(cur, "knowledge_chunks", chunk_rows)
        conn.commit()  # type: ignore[attr-defined]
    return timings


def load_global_knowledge(conn: object) -> int:
    doc_rows, chunk_rows = document_rows(app_docs(), None, static_rows.CREATED)
    with conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute(
            "DELETE FROM knowledge_documents WHERE tenant_id IS NULL AND doc_type = 'app_knowledge'"
        )
        loader.copy_rows(cur, "knowledge_documents", doc_rows)
        loader.copy_rows(cur, "knowledge_chunks", chunk_rows)
    conn.commit()  # type: ignore[attr-defined]
    return len(chunk_rows)


def seed_database(
    database_url: str,
    settings: Settings,
    profiles: list[Profile],
    scale: float,
    end_date: date,
    base_seed: int,
    reset: bool,
    knowledge: bool,
    password: str,
) -> int:
    """Generate and load the chosen tenants into one database. Returns a process exit code."""
    started = time.time()
    engine = create_engine(database_url)
    with Session(engine) as session:
        upsert_reference_data(session)
        session.commit()

    hashes: dict[str, str] = {}
    generated: list[Generated] = []
    for profile in profiles:
        problem = accounts.password_policy_problem(load_catalog(profile), password)
        if problem and not hashes:
            out(f"Warning: DEMO_OWNER_PASSWORD would not pass the app password policy. {problem}")
        hashes[profile.key] = accounts.hash_password(settings, password)
        gen = generate_tenant(profile, base_seed, end_date, scale)
        generated.append(gen)
        out(
            f"generated {profile.key} in {gen.seconds:.1f}s: "
            f"{len(gen.data.rows['sale_lines'])} sale lines, {gen.data.movement_count} movements"
        )

    if scale == 1.0 and base_seed == DEFAULT_BASE_SEED and end_date == DEFAULT_END_DATE:
        write_scenarios_file(end_date, base_seed)

    conn = loader.connect(database_url)
    try:
        ids = [tenant_uuid(g.profile) for g in generated]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE id = ANY(%s)", (ids,))
            existing = [r[0] for r in cur.fetchall()]
            emails = [g.profile.owner_email for g in generated]
            cur.execute("SELECT COUNT(*) FROM users WHERE email = ANY(%s)", (emails,))
            clashing = cur.fetchone()[0]  # type: ignore[index]
            tax_ids = loader.tax_rate_ids(cur)
        conn.commit()
        if (existing or clashing) and not reset:
            out("These tenants already exist. Use --reset to replace them.")
            return 2
        if reset:
            loader.reset_tenants(conn, ids)
        for gen in generated:
            timings = load_generated(
                conn, gen, hashes[gen.profile.key], tax_ids, scale, end_date, knowledge, base_seed
            )
            out(
                f"loaded {gen.profile.key}: "
                + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items())
            )
        if knowledge:
            out(f"global knowledge chunks: {load_global_knowledge(conn)}")
    finally:
        conn.close()
    if reset:
        loader.compact(database_url)

    with Session(engine) as session:
        for gen in generated:
            problems = find_mismatches(session, tenant_uuid(gen.profile))
            out(f"reconciliation {gen.profile.key}: {len(problems)} mismatches")
            if problems:
                return 1
    engine.dispose()
    out(f"done in {time.time() - started:.1f}s")
    return 0


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    base_seed = args.seed if args.seed is not None else settings.seed_base
    if args.end_date.weekday() != 6:
        out("The end date must be a Sunday.")
        return 2
    try:
        password = accounts.owner_password(settings)
    except accounts.MissingPassword as exc:
        out(str(exc))
        return 2
    if args.reset and settings.is_production and not settings.allow_demo_reset:
        out("Reset is blocked in production unless ALLOW_DEMO_RESET is true.")
        return 2
    return seed_database(
        settings.database_url,
        settings,
        resolve_tenants(args.tenants),
        args.scale,
        args.end_date,
        base_seed,
        args.reset,
        not args.no_knowledge,
        password,
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
