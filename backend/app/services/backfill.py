"""Retrospective plans with synthetic owner decisions (`seed-data-spec.md` section 12).

Each past Monday gets a light plan computed with the data cutoff of its own date. For synthetic
tenants an owner is then simulated: about 70 percent of the funded lines are approved as they
are, 20 percent edited with a reason, 10 percent rejected. These decisions are stored with the
Monday as their date, create no purchase orders, and exist only for demo tenants.
"""

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import any_, literal, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import IST
from app.core.db import transaction
from app.core.logging import get_logger
from app.models.intelligence import RecommendationDecision, RecommendationLine, WeeklyReport
from app.services.backfill_docs import write_backfill_docs
from app.services.pipeline import PipelineOutcome, run_pipeline

log = get_logger(__name__)

APPROVE_SHARE = 0.70
EDIT_SHARE = 0.20
EDIT_REASONS = (
    ("shelf_space", "Not enough shelf space"),
    ("supplier_issue", "Problem with the supplier"),
    ("cash_tight", "Cash is tight this week"),
    ("already_ordered", "Already ordered by phone"),
    ("demand_change", "Expecting a change in demand"),
)
REJECT_REASONS = (
    ("not_needed", "Not needed this week"),
    ("already_ordered", "Already ordered by phone"),
    ("supplier_issue", "Problem with the supplier"),
)


def backfill_mondays(last: date, weeks: int) -> list[date]:
    """The Mondays to plan, oldest first, ending with `last`."""
    return [last - timedelta(days=7 * k) for k in range(weeks - 1, -1, -1)]


def _decision_time(monday: date) -> datetime:
    """Monday 8 am IST, as an instant."""
    return datetime.combine(monday, time(8, 0), tzinfo=IST).astimezone(UTC)


def synthetic_decisions(
    session: Session, tenant_id: uuid.UUID, report: WeeklyReport, owner_id: uuid.UUID
) -> int:
    """Simulate the owner for one backfilled report. Returns the number of decisions written."""
    rng = random.Random(f"{tenant_id}|{report.week_start.isoformat()}")  # noqa: S311  simulation, not security
    lines = (
        session.execute(
            select(RecommendationLine)
            .join(
                WeeklyReport,
                (WeeklyReport.tenant_id == RecommendationLine.tenant_id)
                & (WeeklyReport.recommendation_run_id == RecommendationLine.run_id),
            )
            .where(
                WeeklyReport.id == report.id, literal("buy") == any_(RecommendationLine.sections)
            )
            .order_by(RecommendationLine.created_at, RecommendationLine.product_id)
        )
        .scalars()
        .all()
    )
    stamp = _decision_time(report.week_start)
    written = 0
    for line in sorted(lines, key=lambda ln: str(ln.product_id)):
        if line.allocated_qty <= 0:
            continue
        roll = rng.random()
        qty, kind, code, why = line.allocated_qty, "approved", None, None
        if roll >= APPROVE_SHARE + EDIT_SHARE:
            kind, qty = "rejected", Decimal(0)
            code, why = rng.choice(REJECT_REASONS)
        elif roll >= APPROVE_SHARE:
            cut = Decimal(repr(round(rng.uniform(0.10, 0.40), 3)))
            pack = line.pack_size if line.pack_size > 0 else Decimal(1)
            reduced = ((line.allocated_qty * (1 - cut)) / pack).to_integral_value(
                ROUND_FLOOR
            ) * pack
            if reduced >= pack and reduced < line.allocated_qty:
                kind, qty = "edited", reduced
                code, why = rng.choice(EDIT_REASONS)
        session.add(
            RecommendationDecision(
                tenant_id=tenant_id,
                line_id=line.id,
                decided_by=owner_id,
                decision=kind,
                final_qty=qty,
                reason_code=code,
                reason_text=why,
                created_at=stamp,
            )
        )
        written += 1
    session.flush()
    return written


def backfill_tenant(
    factory: sessionmaker[Session], tenant_id: uuid.UUID, last: date, weeks: int
) -> list[PipelineOutcome]:
    """Plan each past Monday, oldest first, so later weeks can reuse earlier selections."""
    outcomes: list[PipelineOutcome] = []
    for monday in backfill_mondays(last, weeks):
        outcome = run_pipeline(
            factory, tenant_id, monday, "light", live=False, rollup=False, backfill=True
        )
        outcomes.append(outcome)
        if outcome.status != "succeeded" or outcome.report_id is None:
            continue
        with factory() as session, transaction(session):
            info = session.execute(
                text(
                    "SELECT t.is_synthetic, "
                    "(SELECT u.id FROM users u WHERE u.tenant_id = t.id "
                    "ORDER BY u.created_at LIMIT 1) "
                    "FROM tenants t WHERE t.id = :t"
                ),
                {"t": tenant_id},
            ).one()
            if not info[0] or info[1] is None:
                continue
            report = session.get(WeeklyReport, outcome.report_id)
            if report is not None:
                exists = session.execute(
                    select(RecommendationDecision.id)
                    .join(
                        RecommendationLine,
                        (RecommendationLine.tenant_id == RecommendationDecision.tenant_id)
                        & (RecommendationLine.id == RecommendationDecision.line_id),
                    )
                    .where(RecommendationLine.run_id == report.recommendation_run_id)
                    .limit(1)
                ).first()
                if exists is None:
                    synthetic_decisions(session, tenant_id, report, info[1])
                    write_backfill_docs(session, tenant_id, report)
    return outcomes
