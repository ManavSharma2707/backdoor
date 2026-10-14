"""Seed validation: `python -m seed.validate [--tenants all] [--scale 1.0]`.

Checks the loaded data against the ledger rules and the planted scenarios
(`seed-data-spec.md` section 15). Exit code 1 when any check fails.
"""

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.services.reconciliation import find_mismatches
from seed.catalog.fmcg_templates import FMCG_CATEGORIES
from seed.catalog.med_templates import MED_CATEGORIES
from seed.model import make_uuid, tenant_uuid
from seed.profiles import (
    DEFAULT_BASE_SEED,
    DEFAULT_END_DATE,
    SCENARIOS_PATH,
    Profile,
    resolve_tenants,
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def tenant_present(session: Session, profile: Profile) -> bool:
    return bool(
        session.execute(
            text("SELECT 1 FROM tenants WHERE id = :t"), {"t": tenant_uuid(profile)}
        ).first()
    )


def check_reconciliation(session: Session, profile: Profile) -> Check:
    problems = find_mismatches(session, tenant_uuid(profile))
    return Check(
        "reconciliation queries return nothing", not problems, f"{len(problems)} mismatches"
    )


def check_counts(session: Session, profile: Profile) -> Check:
    tid = tenant_uuid(profile)
    total = session.execute(
        text("SELECT COUNT(*) FROM products WHERE tenant_id = :t"), {"t": tid}
    ).scalar_one()
    table = MED_CATEGORIES if profile.is_medical else FMCG_CATEGORIES
    expected = {
        slug: (n_a if profile.key.endswith("_a") else n_b)
        for slug, (_, n_a, n_b, _) in table.items()
    }
    rows = session.execute(
        text(
            """
            SELECT c.slug, COUNT(*) FROM products p
            JOIN categories c ON c.tenant_id = p.tenant_id AND c.id = p.category_id
            WHERE p.tenant_id = :t GROUP BY c.slug
            """
        ),
        {"t": tid},
    ).all()
    found = {r[0]: r[1] for r in rows}
    ok = total == profile.skus and found == expected
    return Check("SKU and category counts match the spec", ok, f"{total} of {profile.skus}")


def check_no_negative_stock(session: Session, profile: Profile) -> Check:
    row = session.execute(
        text(
            """
            SELECT COUNT(*) FROM (
                SELECT SUM(quantity_delta) OVER (
                           PARTITION BY product_id, batch_id ORDER BY occurred_at, id) AS running
                FROM inventory_movements WHERE tenant_id = :t
            ) x WHERE running < 0
            """
        ),
        {"t": tenant_uuid(profile)},
    ).scalar_one()
    return Check("no negative balance at any moment", row == 0, f"{row} movements below zero")


def check_receipts_within_orders(session: Session, profile: Profile) -> Check:
    row = session.execute(
        text(
            "SELECT COUNT(*) FROM purchase_order_lines WHERE tenant_id = :t AND quantity_received > quantity_ordered"
        ),
        {"t": tenant_uuid(profile)},
    ).scalar_one()
    return Check("receipts stay within the ordered quantity", row == 0, f"{row} lines over")


def check_batches(session: Session, profile: Profile) -> Check:
    row = session.execute(
        text(
            """
            SELECT COUNT(*) FROM product_batches b
            LEFT JOIN (SELECT batch_id, SUM(quantity_delta) AS q FROM inventory_movements
                       WHERE tenant_id = :t AND movement_type IN ('receipt', 'opening')
                       GROUP BY batch_id) m ON m.batch_id = b.id
            WHERE b.tenant_id = :t AND COALESCE(m.q, 0) <> b.initial_qty
            """
        ),
        {"t": tenant_uuid(profile)},
    ).scalar_one()
    return Check(
        "batch initial quantity equals what was received", row == 0, f"{row} batches differ"
    )


def check_fefo(session: Session, profile: Profile, sample: int = 300) -> Check:
    tid = tenant_uuid(profile)
    lines = session.execute(
        text(
            """
            SELECT m.id, m.product_id, m.batch_id, m.occurred_at, m.business_date, b.expiry_date
            FROM inventory_movements m
            JOIN product_batches b ON b.tenant_id = m.tenant_id AND b.id = m.batch_id
            WHERE m.tenant_id = :t AND m.movement_type = 'sale'
            ORDER BY m.id
            """
        ),
        {"t": tid},
    ).all()
    rng = random.Random(7)
    picked = rng.sample(lines, min(sample, len(lines))) if lines else []
    bad = 0
    for mid, pid, bid, when, d, expiry in picked:
        found = session.execute(
            text(
                """
                SELECT 1 FROM product_batches b2
                WHERE b2.tenant_id = :t AND b2.product_id = :p AND b2.id <> :b
                  AND b2.expiry_date < :exp AND b2.expiry_date > :d
                  AND (SELECT COALESCE(SUM(quantity_delta), 0) FROM inventory_movements x
                       WHERE x.tenant_id = :t AND x.batch_id = b2.id
                         AND (x.occurred_at < :ts OR (x.occurred_at = :ts AND x.id < :mid))) > 0
                LIMIT 1
                """
            ),
            {"t": tid, "p": pid, "b": bid, "exp": expiry, "d": d, "ts": when, "mid": mid},
        ).first()
        bad += 1 if found else 0
    return Check(
        "sampled sales follow earliest expiry first",
        bad == 0,
        f"{bad} of {len(picked)} sampled lines",
    )


def check_rollup(session: Session, profile: Profile) -> Check:
    tid = tenant_uuid(profile)
    n = session.execute(
        text("SELECT COUNT(*) FROM daily_product_stats WHERE tenant_id = :t"), {"t": tid}
    ).scalar_one()
    p = session.execute(
        text("SELECT COUNT(*) FROM products WHERE tenant_id = :t"), {"t": tid}
    ).scalar_one()
    mismatch = session.execute(
        text(
            """
            SELECT COUNT(*) FROM daily_product_stats s
            WHERE s.tenant_id = :t AND s.stat_date = (SELECT MAX(stat_date) FROM daily_product_stats WHERE tenant_id = :t)
              AND s.closing_on_hand <> COALESCE((SELECT SUM(on_hand) FROM stock_balances b
                    WHERE b.tenant_id = :t AND b.product_id = s.product_id), 0)
            """
        ),
        {"t": tid},
    ).scalar_one()
    return Check(
        "daily stats cover every product-day and end on the balances",
        n == p * 546 and mismatch == 0,
        f"{n} rows, {mismatch} closing differences",
    )


def check_sim_closing(session: Session, profile: Profile, gen: Any) -> Check:
    """Closing stock of the simulation equals the ledger for 20 random products on 20 random days."""
    tid = tenant_uuid(profile)
    rng = random.Random(11)
    n_products, n_days = len(gen.catalog.products), gen.plan.n_days
    bad = 0
    for _ in range(20):
        p, t = rng.randrange(n_products), rng.randrange(n_days)
        day: date = gen.plan.start + timedelta(days=t)
        pid = make_uuid(profile.index, 4, p + 1)
        ledger = session.execute(
            text(
                "SELECT COALESCE(SUM(quantity_delta), 0) FROM inventory_movements WHERE tenant_id = :t AND product_id = :p AND business_date <= :d"
            ),
            {"t": tid, "p": pid, "d": day},
        ).scalar_one()
        if int(ledger) != int(gen.data.closing[p, t]):
            bad += 1
    return Check(
        "simulation closing stock equals the ledger (20 samples)", bad == 0, f"{bad} differ"
    )


def check_scenarios(session: Session, profile: Profile) -> list[Check]:
    if not SCENARIOS_PATH.exists():
        return [Check("scenarios.yaml exists", False, "run the seed at full scale first")]
    data = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    mine = data["tenants"].get(profile.key, {})
    tid = tenant_uuid(profile)
    skus: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                if isinstance(v, str) and v[:2] in {"FA", "FB", "MA", "MB"} and "-" in v:
                    skus.add(v)
                else:
                    walk(v)

    walk(mine)
    found = {
        r[0]
        for r in session.execute(
            text("SELECT sku FROM products WHERE tenant_id = :t AND sku = ANY(:s)"),
            {"t": tid, "s": sorted(skus)},
        )
    }
    checks = [Check("every scenario SKU exists", found == skus, f"{len(found)} of {len(skus)}")]
    wanted = {"S02", "S03", "S05", "S06", "S07", "S10", "S11", "S15", "S16", "S17", "S20", "S21"}
    wanted |= {"S08"} if profile.key == "fmcg_a" else {"S09"}
    if profile.key == "fmcg_b" or profile.key == "med_b":
        wanted |= {"S04"}
    if profile.key == "med_a":
        wanted |= {"S12", "S18", "S19"}
    if profile.key == "med_b":
        wanted |= {"S13", "S18", "S19"}
    if not profile.is_medical:
        wanted |= {"S01", "S14"}
    missing = sorted(wanted - set(mine))
    checks.append(
        Check("every scenario for this tenant is listed", not missing, ", ".join(missing))
    )
    return checks


def run_checks(session: Session, profile: Profile, gen: Any | None) -> list[Check]:
    checks = [
        check_reconciliation(session, profile),
        check_counts(session, profile),
        check_no_negative_stock(session, profile),
        check_receipts_within_orders(session, profile),
        check_batches(session, profile),
        check_fefo(session, profile),
        check_rollup(session, profile),
        *check_scenarios(session, profile),
    ]
    if gen is not None:
        checks.append(check_sim_closing(session, profile, gen))
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seed.validate")
    parser.add_argument("--tenants", default="all")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END_DATE)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--skip-sim", action="store_true", help="skip the regeneration based check")
    args = parser.parse_args(argv)
    settings = get_settings()
    base_seed = args.seed if args.seed is not None else settings.seed_base or DEFAULT_BASE_SEED
    failed = 0
    with Session(get_engine()) as session:
        for profile in resolve_tenants(args.tenants):
            if not tenant_present(session, profile):
                out(f"{profile.key}: not loaded, skipped")
                continue
            gen = None
            if not args.skip_sim:
                from seed.generate import generate_tenant

                gen = generate_tenant(profile, base_seed, args.end_date, args.scale)
            out(f"== {profile.key}")
            for check in run_checks(session, profile, gen):
                out(
                    f"  {'ok  ' if check.ok else 'FAIL'} {check.name}"
                    + (f" ({check.detail})" if check.detail and not check.ok else "")
                )
                failed += 0 if check.ok else 1
    out("All checks passed." if not failed else f"{failed} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
