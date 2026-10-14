"""Realism report: `python -m seed.realism` writes `backend/seed/realism_report.md`.

Numbers are read from the loaded database, so the report describes what the engine will see. The
festival uplift is measured on `synthetic_true_demand`, the demand before stock limits.
"""

import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_engine
from seed.model import tenant_uuid
from seed.profiles import PROFILES, REALISM_PATH, Profile

STOCKOUT_TARGET = {
    "fmcg_a": (2.0, 6.0),
    "fmcg_b": (1.0, 3.0),
    "med_a": (1.0, 3.0),
    "med_b": (1.0, 3.0),
}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def q(session: Session, sql: str, **params: Any) -> list[Any]:
    return list(session.execute(text(sql), params).all())


def festival_section(session: Session, profile: Profile) -> list[str]:
    """Measured uplift on true demand next to the multiplier the generator planted."""
    from seed.traits import FMCG_EVENTS, MED_SPURIOUS, NO_EFFECT_PAIRS

    tid = tenant_uuid(profile)
    found = q(
        session,
        """
        WITH ev AS (SELECT * FROM calendar_events WHERE kind = 'festival'
                    AND start_date >= DATE '2025-05-20' AND end_date <= DATE '2026-10-11')
        SELECT ev.event_key, ev.start_date, c.slug, c.name,
               AVG(d.true_demand) FILTER (WHERE d.stat_date BETWEEN ev.start_date AND ev.end_date),
               AVG(d.true_demand) FILTER (WHERE d.stat_date BETWEEN ev.start_date - ev.pre_window_days - 42
                                                                AND ev.start_date - ev.pre_window_days - 14),
               AVG(d.event_multiplier) FILTER (WHERE d.stat_date BETWEEN ev.start_date AND ev.end_date)
        FROM ev JOIN products p ON p.tenant_id = :t
        JOIN categories c ON c.tenant_id = p.tenant_id AND c.id = p.category_id
        JOIN synthetic_true_demand d ON d.tenant_id = :t AND d.product_id = p.id
        GROUP BY ev.event_key, ev.start_date, c.slug, c.name
        """,
        t=tid,
    )
    if profile.is_medical:
        event, slug, _ = MED_SPURIOUS[profile.key]
        wanted = {(event, slug), (event, "analgesics-antipyretics"), (event, "antidiabetics")}
        title = "Festival check on medicines: one chance uplift is planted for a single occurrence, the others stay flat"
    else:
        negatives = set(NO_EFFECT_PAIRS[profile.key])
        wanted = {(e, c) for e, cats in FMCG_EVENTS.items() for c in cats} | negatives
        title = "Festival uplift: measured on true demand next to the planted multiplier (negative cases marked)"
    rows_out = []
    for event, start, slug, name, during, base, planted in sorted(
        found, key=lambda r: (str(r[1]), r[2])
    ):
        if (event, slug) not in wanted or during is None or not base:
            continue
        if not profile.is_medical and float(planted) == 1.0 and (event, slug) not in negatives:
            continue
        mark = "negative case" if (not profile.is_medical and (event, slug) in negatives) else ""
        rows_out.append(
            (
                event,
                str(start),
                name,
                f"{float(during) / float(base):.2f}",
                f"{float(planted):.2f}",
                mark,
            )
        )
    return [
        title,
        "",
        table(("Event", "Starts", "Category", "Measured", "Planted", "Note"), rows_out[:40]),
        "",
    ]


def tenant_section(session: Session, profile: Profile) -> tuple[str, list[str]]:
    tid = tenant_uuid(profile)
    flags: list[str] = []
    days = 546
    sales = q(
        session,
        """
        SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(SUM(tax_total), 0)
        FROM sales WHERE tenant_id = :t AND status = 'completed'
        """,
        t=tid,
    )[0]
    lines_n, units = q(
        session,
        "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM sale_lines l JOIN sales s ON s.tenant_id=l.tenant_id AND s.id=l.sale_id WHERE l.tenant_id=:t AND s.status='completed'",
        t=tid,
    )[0]
    bills, revenue = int(sales[0]), float(sales[1])
    per_day = q(
        session,
        """
        SELECT MIN(r), MAX(r), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r) FROM (
            SELECT SUM(total) AS r FROM sales WHERE tenant_id = :t AND status = 'completed' GROUP BY business_date) x
        """,
        t=tid,
    )[0]
    cogs = float(
        q(
            session,
            "SELECT COALESCE(SUM(-quantity_delta * unit_cost), 0) FROM inventory_movements WHERE tenant_id=:t AND movement_type='sale'",
            t=tid,
        )[0][0]
    )
    margin = 1 - cogs / max(revenue, 1)
    out = [f"## {profile.name} (`{profile.key}`)", "", f"Synthetic data. {profile.story}.", ""]
    summary = [
        ("Bills per day", f"{bills / days:.1f}", f"{profile.bills_per_day:.0f}"),
        ("Lines per bill", f"{lines_n / max(bills, 1):.2f}", f"{profile.lines_per_bill:.1f}"),
        ("Units per bill", f"{float(units) / max(bills, 1):.2f}", ""),
        ("Sales per day (₹, tax inclusive)", f"{revenue / days:,.0f}", ""),
        ("Average bill (₹)", f"{revenue / max(bills, 1):,.0f}", ""),
        (
            "Quietest, median, busiest day (₹)",
            f"{float(per_day[0]):,.0f} / {float(per_day[2]):,.0f} / {float(per_day[1]):,.0f}",
            "",
        ),
        (
            "Gross margin (price and cost both include GST)",
            f"{margin * 100:.1f} percent",
            "under 40",
        ),
    ]
    out += [table(("Measure", "Value", "Target"), summary), ""]
    if abs(bills / days - profile.bills_per_day) > 0.25 * profile.bills_per_day:
        flags.append(
            f"{profile.key}: bills per day {bills / days:.1f} is far from {profile.bills_per_day:.0f}"
        )
    if margin > 0.40:
        flags.append(f"{profile.key}: gross margin {margin * 100:.1f} percent is too high")

    cat = q(
        session,
        """
        SELECT c.name, SUM(l.line_total) FROM sale_lines l
        JOIN sales s ON s.tenant_id=l.tenant_id AND s.id=l.sale_id
        JOIN products p ON p.tenant_id=l.tenant_id AND p.id=l.product_id
        JOIN categories c ON c.tenant_id=p.tenant_id AND c.id=p.category_id
        WHERE l.tenant_id=:t AND s.status='completed' GROUP BY c.name ORDER BY 2 DESC
        """,
        t=tid,
    )
    total = sum(float(r[1]) for r in cat) or 1.0
    out += [
        "Share of sales by category (top 8)",
        "",
        table(
            ("Category", "Share"),
            [(r[0], f"{float(r[1]) / total * 100:.1f} percent") for r in cat[:8]],
        ),
        "",
    ]

    st = q(
        session,
        """
        SELECT availability_state, COUNT(*) FROM daily_product_stats
        WHERE tenant_id=:t AND availability_state <> 'not_launched' GROUP BY 1
        """,
        t=tid,
    )
    st_total = sum(r[1] for r in st) or 1
    shares = {r[0]: r[1] / st_total * 100 for r in st}
    lo, hi = STOCKOUT_TARGET[profile.key]
    out += [
        "Availability across all product days",
        "",
        table(
            ("State", "Share"),
            [(k, f"{v:.2f} percent") for k, v in sorted(shares.items())],
        ),
        "",
        f"Out of stock all day: {shares.get('stocked_out_all_day', 0):.2f} percent (target {lo:.0f} to {hi:.0f}).",
        "",
    ]
    if not lo - 0.5 <= shares.get("stocked_out_all_day", 0) <= hi + 0.5:
        flags.append(
            f"{profile.key}: out of stock share {shares.get('stocked_out_all_day', 0):.2f} is outside {lo} to {hi}"
        )

    loss = q(
        session,
        """
        SELECT movement_type, COALESCE(SUM(-quantity_delta * unit_cost), 0), COUNT(*)
        FROM inventory_movements WHERE tenant_id=:t
          AND movement_type IN ('expiry_writeoff', 'supplier_return', 'damage') GROUP BY 1
        """,
        t=tid,
    )
    loss_rows = [
        (r[0], f"₹{float(r[1]):,.0f}", f"{float(r[1]) / max(cogs, 1) * 100:.2f} percent", r[2])
        for r in loss
    ]
    out += [
        "Stock removed other than by sale, at cost",
        "",
        table(("Type", "Value", "Share of cost of goods sold", "Events"), loss_rows),
        "",
    ]

    wd = q(
        session,
        "SELECT EXTRACT(ISODOW FROM stat_date)::int, SUM(units_sold) FROM daily_product_stats WHERE tenant_id=:t GROUP BY 1 ORDER BY 1",
        t=tid,
    )
    mean = sum(float(r[1]) for r in wd) / 7.0 or 1.0
    out += [
        "Weekday profile of units sold (1.00 is an average day)",
        "",
        table(WEEKDAYS, [[f"{float(r[1]) / mean:.2f}" for r in wd]]),
        "",
    ]

    dom = q(
        session,
        """
        SELECT CASE WHEN EXTRACT(DAY FROM stat_date) <= 7 THEN 'days 1 to 7' ELSE 'days 8 to 31' END, AVG(units_sold)
        FROM daily_product_stats s JOIN products p ON p.tenant_id=s.tenant_id AND p.id=s.product_id
        JOIN categories c ON c.tenant_id=p.tenant_id AND c.id=p.category_id
        WHERE s.tenant_id=:t AND c.slug = ANY(:slugs) AND s.availability_state='available'
        GROUP BY 1 ORDER BY 1
        """,
        t=tid,
        slugs=["antidiabetics", "cardiac-antihypertensives", "thyroid-chronic"]
        if profile.is_medical
        else ["atta-rice-grains", "pulses-dal", "edible-oils-ghee", "sugar-salt-jaggery"],
    )
    if len(dom) == 2:
        out += [
            f"Month start refill pattern: units per product day are {float(dom[0][1]) / float(dom[1][1]):.2f} times higher in days 1 to 7 than later in the month.",
            "",
        ]

    out += festival_section(session, profile)
    return "\n".join(out), flags


def build_report(session: Session) -> str:
    sections: list[str] = []
    all_flags: list[str] = []
    for profile in PROFILES.values():
        present = session.execute(
            text("SELECT 1 FROM tenants WHERE id = :t"), {"t": tenant_uuid(profile)}
        ).first()
        if not present:
            continue
        body, flags = tenant_section(session, profile)
        sections.append(body)
        all_flags += flags
    header = [
        "# Realism report",
        "",
        "Generated by `python -m seed.realism` from the loaded database. All data is synthetic.",
        "Uplift ratios are rough: they compare the festival days with the average of earlier weeks and include weekday mix and season.",
        "",
    ]
    footer = (
        ["## Plausibility flags", "", *(f"- {f}" for f in all_flags)]
        if all_flags
        else ["## Plausibility flags", "", "None. All checked numbers sit inside their targets."]
    )
    return "\n".join(header) + "\n" + "\n\n".join(sections) + "\n\n" + "\n".join(footer) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    with Session(get_engine()) as session:
        report = build_report(session)
    REALISM_PATH.write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {REALISM_PATH}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
