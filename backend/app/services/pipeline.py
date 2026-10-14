"""The Monday pipeline (`engine-spec.md` section 15): lock, roll up, compute, persist.

One run per tenant and week. The compute step reads, the persist step writes everything in a
single transaction, and `job_runs` records the outcome in its own transactions so a failure is
visible even though its rows were rolled back.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.core.db import transaction
from app.core.logging import get_logger
from app.core.timeutil import data_cutoff_for_week, week_start
from app.engine import dq
from app.engine.constants import ENGINE_VERSION, MODEL_NAME, RETAINED_FORECAST_RUNS
from app.engine.plan import Line
from app.engine.report_builder import ReportInput, build_snapshot
from app.models.intelligence import (
    ForecastValue,
    RecommendationLine,
    RecommendationRun,
    WeeklyReport,
)
from app.models.ops import JobRun
from app.services import forecast_store
from app.services.dq_service import DqStore
from app.services.plan_compute import ComputeResult, compute_plan
from app.services.rollup import RollupService

log = get_logger(__name__)

JOB_NAME = "monday_report"
KEPT_BACKTESTS = 4
DQ_STOCK_CODES = frozenset({"NEGATIVE_STOCK", "BATCH_QTY_MISMATCH"})


@dataclass
class PipelineOutcome:
    tenant_id: uuid.UUID
    as_of: date
    status: str  # succeeded, skipped or failed
    reason: str | None = None
    report_id: uuid.UUID | None = None
    version: int | None = None
    job_run_id: uuid.UUID | None = None
    lines: int = 0
    timings: dict[str, float] = field(default_factory=dict)
    error: str | None = None


def run_key(as_of: date) -> str:
    return f"{JOB_NAME}:{as_of.isoformat()}"


def monday_of(day: date) -> date:
    return week_start(day)


def _lock_key(tenant_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"{JOB_NAME}|{tenant_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class TenantLock:
    """A session level advisory lock held for the whole run, on its own connection."""

    def __init__(self, factory: sessionmaker[Session], tenant_id: uuid.UUID) -> None:
        self.session = factory()
        self.key = _lock_key(tenant_id)
        self.held = False

    def acquire(self) -> bool:
        self.held = bool(
            self.session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar()
        )
        return self.held

    def release(self) -> None:
        try:
            if self.held:
                self.session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
        finally:
            self.session.rollback()
            self.session.close()
            self.held = False


# ----------------------------------------------------------------------------- job_runs


def start_job(
    factory: sessionmaker[Session], tenant_id: uuid.UUID, as_of: date, *, force: bool, profile: str
) -> tuple[uuid.UUID | None, str | None]:
    """Create or take over the `job_runs` row. Returns (id, None) or (None, reason to skip)."""
    with factory() as session, transaction(session):
        current = session.execute(
            select(WeeklyReport.id).where(
                WeeklyReport.tenant_id == tenant_id,
                WeeklyReport.week_start == as_of,
                WeeklyReport.is_current,
                WeeklyReport.status == "ready",
            )
        ).first()
        row = session.execute(
            select(JobRun)
            .where(
                JobRun.job_name == JOB_NAME,
                JobRun.run_key == run_key(as_of),
                JobRun.tenant_id == tenant_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if not force and (current is not None or (row is not None and row.status == "succeeded")):
            return None, "A report for this week already exists."
        if row is None:
            row = JobRun(
                tenant_id=tenant_id,
                job_name=JOB_NAME,
                run_key=run_key(as_of),
                status="running",
                attempts=1,
                started_at=now_utc(),
                result={"profile": profile},
            )
            session.add(row)
        else:
            row.status = "running"
            row.attempts += 1
            row.started_at = now_utc()
            row.finished_at = None
            row.error = None
            row.result = {"profile": profile}
        session.flush()
        return row.id, None


def _finish_job(
    factory: sessionmaker[Session],
    job_id: uuid.UUID,
    status: str,
    result: dict[str, Any],
    error: str | None,
) -> None:
    with factory() as session, transaction(session):
        session.execute(
            update(JobRun)
            .where(JobRun.id == job_id)
            .values(status=status, finished_at=now_utc(), result=result, error=error)
        )


# ----------------------------------------------------------------------------- persistence


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal | date | datetime):
        return str(value)
    raise TypeError(type(value).__name__)


def _to_json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def _dec(value: float, places: int = 3) -> Decimal:
    return Decimal(repr(round(value, places)))


def write_forecast_values(
    session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID, result: ComputeResult
) -> int:
    rows: list[dict[str, Any]] = []
    for pid, fc in zip(result.history.product_ids, result.forecasts, strict=True):
        for d in range(len(fc.yhat)):
            key = fc.event_keys[d] if d < len(fc.event_keys) else None
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "product_id": pid,
                    "forecast_date": result.as_of + timedelta(days=d),
                    "yhat": _dec(float(fc.yhat[d])),
                    "yhat_lower": _dec(float(fc.lower[d])),
                    "yhat_upper": _dec(float(fc.upper[d])),
                    "method": fc.method,
                    "event_multiplier": Decimal(repr(round(float(fc.multiplier[d]), 3))),
                    "event_key": key,
                }
            )
    for i in range(0, len(rows), 2000):
        session.execute(insert(ForecastValue), rows[i : i + 2000])
    return len(rows)


def _line_row(
    tenant_id: uuid.UUID, run_id: uuid.UUID, line_id: uuid.UUID, ln: Line, text_of: str
) -> RecommendationLine:
    r = ln.replen
    return RecommendationLine(
        id=line_id,
        tenant_id=tenant_id,
        run_id=run_id,
        product_id=ln.product.id,
        supplier_id=ln.supplier.id if ln.supplier else None,
        sections=ln.sections,
        protection_days=r.protection_days,
        lead_time_days=ln.lead.total_days,
        lead_time_source=ln.lead.source,
        avg_daily_forecast=_dec(ln.avg_daily_forecast, 4),
        demand_7d=_dec(ln.demand_7d),
        demand_protection=_dec(r.demand_protection),
        on_hand_usable=_dec(ln.on_hand_usable),
        expected_expiry_loss=_dec(ln.expected_expiry_loss),
        incoming_confirmed=_dec(ln.stock.incoming_confirmed),
        incoming_excluded_overdue=_dec(ln.stock.incoming_overdue),
        reserved=_dec(ln.stock.reserved),
        inventory_position=_dec(r.inventory_position),
        safety_stock=_dec(r.safety_stock),
        target_level=_dec(r.target_level),
        raw_qty=_dec(r.raw_qty),
        moq_units=ln.moq_units,
        pack_size=ln.pack_size,
        suggested_qty=_dec(ln.suggested_qty),
        allocated_qty=_dec(ln.allocated_qty),
        pack_excess_qty=_dec(r.pack_excess_qty),
        unit_cost=ln.unit_cost,
        est_spend=ln.est_spend,
        unfunded_qty=_dec(ln.unfunded_qty),
        budget_limited=ln.budget_limited,
        stockout_probability=Decimal(repr(round(ln.stockout_probability, 3))),
        projected_stockout_date=ln.projected_stockout_date,
        days_of_cover=None if ln.days_of_cover is None else _dec(ln.days_of_cover, 2),
        risk_level=ln.risk_level,
        confidence=ln.confidence,
        forecast_method=ln.forecast.method,
        wape=None if ln.wape is None else _dec(min(ln.wape, 9999.0), 4),
        priority_score=None if ln.priority_score is None else _dec(ln.priority_score, 4),
        priority_components=_to_json(ln.priority_components),
        expiry_exposure_qty=_dec(ln.expiry_exposure_qty),
        expiry_exposure_value=ln.expiry_exposure_value,
        excess_qty=_dec(ln.excess_qty),
        excess_value=ln.excess_value,
        stock_status=ln.stock_status,
        event_keys=ln.event_keys,
        reason_codes=ln.reason_codes,
        reason_text=text_of,
        provenance=ln.provenance,
        warnings=ln.warnings,
    )


def persist_result(
    session: Session,
    tenant_id: uuid.UUID,
    result: ComputeResult,
    *,
    live: bool,
    force: bool,
    job_id: uuid.UUID | None,
    backfill: bool = False,
) -> tuple[WeeklyReport, int]:
    """Write the whole outcome in one transaction. Raises on any problem, leaving nothing."""
    as_of = result.as_of
    cutoff = data_cutoff_for_week(as_of)
    horizon = result.settings.forecast_horizon_days
    with transaction(session):
        version_id = forecast_store.ensure_model_version(session)
        selection_run_id: uuid.UUID | None = (
            result.selection_run.id if result.selection_run else None
        )
        if result.backtest is not None:
            bt_run = forecast_store.create_run(
                session,
                tenant_id,
                kind="backtest",
                profile=result.profile,
                as_of=as_of,
                horizon=horizon,
                config={"origins": result.selection.n_origins, "global_model": result.global_model},
            )
            forecast_store.save_selection(session, tenant_id, bt_run, result.selection)
            forecast_store.finish_run(bt_run, "succeeded")
            selection_run_id = bt_run.id
        if live and result.effects_fresh:
            forecast_store.save_effects(session, tenant_id, result.effects, result.category_ids)
        fc_run = forecast_store.create_run(
            session,
            tenant_id,
            kind="weekly",
            profile=result.profile,
            as_of=as_of,
            horizon=horizon,
            config={
                "censor_policy": result.settings.censor_policy,
                "selection_source": result.selection_source,
                "selection_run_id": str(selection_run_id) if selection_run_id else None,
                "effects_fresh": result.effects_fresh,
                "global_model": result.global_model,
                "timings": result.timings,
                "notes": result.notes,
                "backfill": backfill,
            },
        )
        write_forecast_values(session, tenant_id, fc_run.id, result)
        forecast_store.finish_run(fc_run, "succeeded")

        checked = [c for c in dq.CODES if live or c not in DQ_STOCK_CODES]
        if live:
            DqStore(session, tenant_id).save(result.findings, checked, fc_run.id)

        rec_run = RecommendationRun(
            tenant_id=tenant_id,
            forecast_run_id=fc_run.id,
            as_of_date=as_of,
            data_cutoff=cutoff,
            budget=result.plan.budget.budget,
            model_version_id=version_id,
            status="running",
            settings_snapshot=_to_json(
                {
                    "weekly_budget": result.settings.weekly_budget,
                    "service_level": result.settings.service_level,
                    "review_period_days": result.settings.review_period_days,
                    "default_lead_time_days": result.settings.default_lead_time_days,
                    "pack_rounding": result.settings.pack_rounding,
                    "priority_weights": result.settings.priority_weights,
                }
            ),
            started_at=now_utc(),
        )
        session.add(rec_run)
        session.flush()
        line_ids = {ln.key: uuid.uuid4() for ln in result.plan.lines}
        ri = ReportInput(
            tenant_name=result.tenant.name,
            business_type=result.tenant.business_type,
            is_synthetic=result.tenant.is_synthetic,
            as_of=as_of,
            data_cutoff=cutoff,
            model_version=f"{MODEL_NAME} {ENGINE_VERSION}",
            profile=result.profile,
            plan=result.plan,
            events=result.events,
            effects=result.effects,
            category_names={str(p.category_id): p.category_name for p in result.products},
            selection=result.selection,
            findings=result.findings,
            line_ids=line_ids,
            selection_source=result.selection_source,
            notes=result.notes,
            global_model=result.global_model,
        )
        payload = build_snapshot(ri)
        payload["backfill"] = backfill
        for ln in result.plan.lines:
            text_of = payload["lines"][str(line_ids[ln.key])]["reason_text"]
            session.add(_line_row(tenant_id, rec_run.id, line_ids[ln.key], ln, text_of))
        session.flush()
        rec_run.summary = payload["summary"]
        rec_run.status = "succeeded"
        rec_run.finished_at = now_utc()

        previous = (
            session.execute(
                select(WeeklyReport)
                .where(WeeklyReport.tenant_id == tenant_id, WeeklyReport.week_start == as_of)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        version = max((r.version for r in previous), default=0) + 1
        for old in previous:
            if old.is_current:
                old.is_current = False
        session.flush()
        report = WeeklyReport(
            tenant_id=tenant_id,
            week_start=as_of,
            version=version,
            is_current=True,
            recommendation_run_id=rec_run.id,
            forecast_run_id=fc_run.id,
            data_cutoff=cutoff,
            status="ready",
            payload=payload,
            summary=payload["summary"],
            warnings=payload["data_notes"],
            model_version=f"{MODEL_NAME} {ENGINE_VERSION}",
            generated_at=now_utc(),
        )
        session.add(report)
        session.flush()
        prune(session, tenant_id)
    return report, len(result.plan.lines)


def prune(session: Session, tenant_id: uuid.UUID) -> None:
    """Retention: the newest 8 forecast runs and 4 backtests, and expired idempotency keys."""
    forecast_store.prune_forecasts(session, tenant_id, RETAINED_FORECAST_RUNS, KEPT_BACKTESTS)
    session.execute(
        text("DELETE FROM idempotency_keys WHERE tenant_id = :t AND expires_at < :now"),
        {"t": tenant_id, "now": now_utc()},
    )


# ----------------------------------------------------------------------------- orchestration


def run_pipeline(
    factory: sessionmaker[Session],
    tenant_id: uuid.UUID,
    as_of: date,
    profile: str = "light",
    *,
    force: bool = False,
    live: bool = True,
    rollup: bool = True,
    backfill: bool = False,
    job_id: uuid.UUID | None = None,
    stop: Callable[[], bool] | None = None,
) -> PipelineOutcome:
    """Run the pipeline for one tenant and one Monday and store the report.

    Skips (and says so) when the week already has a current report and `force` is not set. With
    `force` a new version is written and becomes the current one. Any error rolls back the plan
    rows and marks the job failed. A caller that already created the job row (the API does, to
    answer with its id) passes it as `job_id`.
    """
    outcome = PipelineOutcome(tenant_id, as_of, "failed")
    lock = TenantLock(factory, tenant_id)
    if not lock.acquire():
        lock.release()
        outcome.status, outcome.reason = "skipped", "Another run for this business is in progress."
        return outcome
    try:
        if job_id is None:
            job_id, skip = start_job(factory, tenant_id, as_of, force=force, profile=profile)
            if job_id is None:
                outcome.status, outcome.reason = "skipped", skip
                return outcome
        outcome.job_run_id = job_id
        with factory() as session:
            if rollup:
                with transaction(session):
                    RollupService(session, tenant_id).update(as_of - timedelta(days=1))
            result = compute_plan(session, tenant_id, as_of, profile, live=live, stop=stop)
            report, n_lines = persist_result(
                session,
                tenant_id,
                result,
                live=live,
                force=force,
                job_id=job_id,
                backfill=backfill,
            )
        outcome.status = "succeeded"
        outcome.report_id, outcome.version, outcome.lines = report.id, report.version, n_lines
        outcome.timings = result.timings
        _finish_job(
            factory,
            job_id,
            "succeeded",
            {
                "profile": profile,
                "report_id": str(report.id),
                "version": report.version,
                "lines": n_lines,
                "timings": result.timings,
                "selection": result.selection_source,
                "global_model": _to_json(result.global_model),
            },
            None,
        )
        log.info(
            "pipeline.done",
            tenant_id=str(tenant_id),
            as_of=as_of.isoformat(),
            profile=profile,
            version=report.version,
            lines=n_lines,
        )
    except Exception as exc:
        log.error(
            "pipeline.failed", tenant_id=str(tenant_id), as_of=as_of.isoformat(), error=str(exc)
        )
        outcome.status, outcome.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        if job_id is not None:
            _finish_job(factory, job_id, "failed", {"profile": profile}, outcome.error)
    finally:
        lock.release()
    return outcome


def tenant_ids(factory: sessionmaker[Session], ref: str) -> list[tuple[uuid.UUID, str]]:
    """Tenants named by id, slug or `all`."""
    with factory() as session:
        if ref == "all":
            rows = session.execute(
                text("SELECT id, slug FROM tenants WHERE is_active ORDER BY slug")
            ).all()
        else:
            try:
                key = uuid.UUID(ref)
                rows = session.execute(
                    text("SELECT id, slug FROM tenants WHERE id = :k"), {"k": key}
                ).all()
            except ValueError:
                rows = session.execute(
                    text("SELECT id, slug FROM tenants WHERE slug = :k"), {"k": ref}
                ).all()
    return [(r[0], r[1]) for r in rows]


def latest_current_report(
    session: Session, tenant_id: uuid.UUID, week: date
) -> WeeklyReport | None:
    return session.execute(
        select(WeeklyReport).where(
            WeeklyReport.tenant_id == tenant_id,
            WeeklyReport.week_start == week,
            WeeklyReport.is_current,
        )
    ).scalar_one_or_none()
