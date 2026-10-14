"""Corpus documents for the backfilled plans (`seed-data-spec.md` section 11, P4.26).

`decision_memory`: one short document per synthetic decision that carries a reason.
`report_narrative`: one short template narrative per backfilled weekly report.
Embeddings stay empty until Prompt 7. Everything here is synthetic and labelled so.
"""

import hashlib
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import any_, literal, select
from sqlalchemy.orm import Session

from app.models.agents import KnowledgeChunk, KnowledgeDocument
from app.models.catalogue import Product
from app.models.intelligence import RecommendationDecision, RecommendationLine, WeeklyReport

SYNTHETIC_NOTE = "Synthetic demo record."
REASON_PHRASES = {
    "shelf_space": "there was not enough shelf space",
    "supplier_issue": "of a problem with the supplier",
    "cash_tight": "cash was tight that week",
    "already_ordered": "the item was already ordered by phone",
    "demand_change": "a change in demand was expected",
    "not_needed": "it was not needed that week",
}


def display_date(day: date) -> str:
    return f"{day.day} {day.strftime('%b')} {day.year}"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _qty(value: Decimal) -> str:
    return str(int(value)) if value == value.to_integral_value() else f"{value:.1f}"


def _add(
    session: Session,
    tenant_id: uuid.UUID,
    doc_type: str,
    title: str,
    source_ref: str,
    text: str,
    metadata: dict[str, Any],
) -> bool:
    """Insert one document with a single chunk unless the same one exists."""
    digest = _hash(text)
    exists = session.execute(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.doc_type == doc_type,
            KnowledgeDocument.source_ref == source_ref,
            KnowledgeDocument.content_hash == digest,
        )
    ).first()
    if exists is not None:
        return False
    doc = KnowledgeDocument(
        tenant_id=tenant_id,
        doc_type=doc_type,
        title=title,
        source_ref=source_ref,
        metadata_=metadata,
        content_hash=digest,
    )
    session.add(doc)
    session.flush()
    session.add(
        KnowledgeChunk(
            document_id=doc.id,
            tenant_id=tenant_id,
            chunk_index=0,
            content=text,
            token_count=max(1, len(text) // 4),
            metadata_={"doc_type": doc_type, "title": title},
        )
    )
    return True


def decision_memory_text(
    name: str, unit: str, week: str, decision: str, was: Decimal, now: Decimal, reason: str
) -> str:
    phrase = REASON_PHRASES.get(reason, reason.replace("_", " "))
    if decision == "rejected":
        body = (
            f"On {week} you did not order {name}. "
            f"The plan suggested {_qty(was)} {unit}, but {phrase}."
        )
    else:
        body = (
            f"On {week} you reduced {name} from {_qty(was)} to {_qty(now)} {unit} because {phrase}."
        )
    return f"{body} {SYNTHETIC_NOTE}"


def narrative_text(week: str, summary: dict[str, Any], decided: dict[str, int]) -> str:
    parts = [
        f"Plan for the week of {week}. The plan recommended {summary.get('lines_buy', 0)} items "
        f"to buy, spending {summary.get('planned_spend', '0')} rupees of a "
        f"{summary.get('budget', '0')} rupee budget.",
    ]
    short = Decimal(str(summary.get("shortfall", "0")))
    if short > 0:
        parts.append(
            f"Needed spend was {summary.get('needed_spend')} rupees, so some lines were not funded."
        )
    parts.append(
        f"{summary.get('critical_count', 0)} items were critical and "
        f"{summary.get('high_count', 0)} were high risk."
    )
    if decided:
        parts.append(
            f"Decisions: {decided.get('approved', 0)} approved as planned, "
            f"{decided.get('edited', 0)} edited and {decided.get('rejected', 0)} rejected."
        )
    return " ".join(parts) + f" {SYNTHETIC_NOTE}"


def write_backfill_docs(session: Session, tenant_id: uuid.UUID, report: WeeklyReport) -> int:
    """Add the documents for one backfilled report. Returns how many were created."""
    week = display_date(report.week_start)
    rows: Sequence[Any] = session.execute(
        select(RecommendationLine, RecommendationDecision, Product.name, Product.base_unit)
        .join(
            RecommendationDecision,
            (RecommendationDecision.tenant_id == RecommendationLine.tenant_id)
            & (RecommendationDecision.line_id == RecommendationLine.id),
        )
        .join(
            Product,
            (Product.tenant_id == RecommendationLine.tenant_id)
            & (Product.id == RecommendationLine.product_id),
        )
        .where(
            RecommendationLine.tenant_id == tenant_id,
            RecommendationLine.run_id == report.recommendation_run_id,
            RecommendationDecision.superseded_at.is_(None),
            literal("buy") == any_(RecommendationLine.sections),
        )
        .order_by(Product.name)
    ).all()
    created = 0
    counts: dict[str, int] = {}
    for line, decision, name, unit in rows:
        counts[decision.decision] = counts.get(decision.decision, 0) + 1
        if decision.reason_code is None:
            continue
        text = decision_memory_text(
            name,
            unit,
            week,
            decision.decision,
            line.allocated_qty,
            decision.final_qty,
            decision.reason_code,
        )
        created += _add(
            session,
            tenant_id,
            "decision_memory",
            f"{name}, {week}",
            f"decision:{decision.id}",
            text,
            {"week_start": report.week_start.isoformat(), "synthetic": True},
        )
    created += _add(
        session,
        tenant_id,
        "report_narrative",
        f"Weekly plan, {week}",
        f"report:{report.id}",
        narrative_text(week, report.summary, counts),
        {"week_start": report.week_start.isoformat(), "synthetic": True},
    )
    return created
