"""Recompute the data quality issues on demand (`POST /data-quality/run`)."""

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.core.db import transaction
from app.engine.deadstock import abc_classes
from app.engine.forecast import training_data
from app.services.dq_service import DqStore
from app.services.pipeline import monday_of
from app.services.plan_compute import PRE_PLAN_CODES, pre_findings
from app.services.plan_data import PlanLoader
from app.services.rollup import RollupService

CHECKED = (
    *PRE_PLAN_CODES,
    "PO_OVERDUE",
    "RECEIPT_EXCEEDS_ORDER",
    "DUPLICATE_SALE_SUSPECT",
    "UNRECORDED_STOCKOUT_SUSPECTED",
    "CALENDAR_STALE",
    "NEGATIVE_STOCK",
    "BATCH_QTY_MISMATCH",
)


def run_checks(session: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Roll the days up, run the checks that do not need a forecast and store the findings."""
    as_of = monday_of(today_ist())
    with transaction(session):
        RollupService(session, tenant_id).update(as_of - timedelta(days=1))
        loader = PlanLoader(session, tenant_id, as_of)
        settings = loader.settings()
        suppliers = loader.suppliers()
        history = loader.history()
        products = [
            {p.id: p for p in loader.products(history, suppliers)}[pid]
            for pid in history.product_ids
        ]
        events = loader.calendar_events()
        training = training_data(
            history.units, history.codes, history.promo, history.start, settings.censor_policy
        )
        revenue = {
            pid: float(history.revenue[i, -90:].sum()) for i, pid in enumerate(history.product_ids)
        }
        labels = {p.id: f"{p.name} ({p.sku})" for p in products}
        findings = pre_findings(
            session,
            tenant_id,
            as_of,
            products,
            suppliers,
            settings,
            abc_classes(revenue),
            training,
            history,
            events,
            True,
            labels,
        )
        counts = DqStore(session, tenant_id).save(findings, CHECKED, None)
    return counts
