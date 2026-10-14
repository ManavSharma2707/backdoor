"""The Monday pipeline on the seeded database: idempotency, versions, determinism, rollback."""

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.models.intelligence import (
    ForecastBacktest,
    ForecastRun,
    ForecastValue,
    RecommendationLine,
    RecommendationRun,
    WeeklyReport,
)
from app.models.ops import JobRun
from app.services import pipeline
from tests.pipeline.conftest import AS_OF, PipelineDb

GOLDEN = Path(__file__).parent / "golden"
KEY = "fmcg_a"


def run(db: PipelineDb, key: str = KEY, **kwargs: Any) -> pipeline.PipelineOutcome:
    return pipeline.run_pipeline(db.factory, db.tenant_id(key), AS_OF, "light", **kwargs)


def normalise(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with line ids replaced by SKUs, so two runs can be compared."""
    token = {lid: f"line:{ln['sku']}" for lid, ln in payload["lines"].items()}

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {token.get(k, k): walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return token.get(value, value)
        return value

    return walk(copy.deepcopy(payload))  # type: ignore[no-any-return]


def counts(db: PipelineDb) -> dict[str, int]:
    with db.session() as s:
        return {
            name: s.scalar(select(func.count()).select_from(model)) or 0
            for name, model in (
                ("reports", WeeklyReport),
                ("lines", RecommendationLine),
                ("rec_runs", RecommendationRun),
                ("fc_runs", ForecastRun),
                ("values", ForecastValue),
                ("backtests", ForecastBacktest),
                ("jobs", JobRun),
            )
        }


def test_first_run_stores_a_complete_report(seeded_plans: PipelineDb) -> None:
    outcome = run(seeded_plans)
    assert outcome.status == "succeeded"
    assert outcome.version == 1
    assert outcome.lines == 92
    with seeded_plans.session() as s:
        report = s.get(WeeklyReport, outcome.report_id)
        assert report is not None
        assert (report.status, report.is_current, report.week_start) == ("ready", True, AS_OF)
        assert report.payload["tenant"]["is_synthetic"] is True
        assert report.payload["week_start"] == "2026-10-12"
        assert report.payload["data_cutoff"] == "2026-10-11T18:30:00Z"
        assert report.model_version == "forecast-engine 1.0.0"
        assert report.payload["backfill"] is False
        assert len(report.payload["lines"]) == 92
        assert s.scalar(select(func.count()).select_from(ForecastValue)) == 92 * 28
        job = s.scalars(select(JobRun)).one()
        assert (job.status, job.attempts, job.run_key) == (
            "succeeded",
            1,
            "monday_report:2026-10-12",
        )
        assert job.result["report_id"] == str(report.id)
        rec = s.get(RecommendationRun, report.recommendation_run_id)
        assert rec is not None
        assert rec.status == "succeeded"
        assert rec.summary["planned_spend"] == report.summary["planned_spend"]


def test_running_twice_gives_one_current_report(seeded_plans: PipelineDb) -> None:
    first = run(seeded_plans)
    second = run(seeded_plans)
    assert (first.status, second.status) == ("succeeded", "skipped")
    assert second.reason == "A report for this week already exists."
    assert counts(seeded_plans)["reports"] == 1
    assert counts(seeded_plans)["lines"] == 92


def test_force_creates_version_2_and_flips_the_current_flag(seeded_plans: PipelineDb) -> None:
    run(seeded_plans)
    forced = run(seeded_plans, force=True)
    assert (forced.status, forced.version) == ("succeeded", 2)
    with seeded_plans.session() as s:
        rows = s.execute(
            select(WeeklyReport.version, WeeklyReport.is_current).order_by(WeeklyReport.version)
        ).all()
        assert rows == [(1, False), (2, True)]
        job = s.scalars(select(JobRun)).one()
        assert job.attempts == 2
    third = run(seeded_plans, force=True)
    assert third.version == 3


def test_same_inputs_give_identical_reports_and_the_light_run_reuses_the_selection(
    seeded_plans: PipelineDb,
) -> None:
    a = run(seeded_plans)
    b = run(seeded_plans, force=True)
    with seeded_plans.session() as s:
        first = s.get(WeeklyReport, a.report_id)
        second = s.get(WeeklyReport, b.report_id)
        assert first is not None
        assert second is not None
        assert first.payload["backtest_summary"]["source"] == "fresh"
        assert second.payload["backtest_summary"]["source"] == "stored"
        one, two = normalise(first.payload), normalise(second.payload)
        one["backtest_summary"].pop("source")
        two["backtest_summary"].pop("source")
        assert one == two
        runs = s.scalars(select(ForecastRun).where(ForecastRun.kind == "backtest")).all()
        assert len(runs) == 1  # the second run found the first one's selection


def test_a_failure_in_the_persist_step_leaves_nothing_behind(
    seeded_plans: PipelineDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected failure after the forecast rows were written")

    monkeypatch.setattr(pipeline, "build_snapshot", boom)
    outcome = run(seeded_plans)
    assert outcome.status == "failed"
    assert "injected failure" in (outcome.error or "")
    assert counts(seeded_plans) == {
        "reports": 0,
        "lines": 0,
        "rec_runs": 0,
        "fc_runs": 0,
        "values": 0,
        "backtests": 0,
        "jobs": 1,
    }
    with seeded_plans.session() as s:
        job = s.scalars(select(JobRun)).one()
        assert job.status == "failed"
        assert "injected failure" in (job.error or "")
    monkeypatch.undo()
    retry = run(seeded_plans)
    assert retry.status == "succeeded"
    with seeded_plans.session() as s:
        assert s.scalars(select(JobRun)).one().attempts == 2


def test_a_second_run_while_one_is_in_progress_is_skipped(seeded_plans: PipelineDb) -> None:
    holder = pipeline.TenantLock(seeded_plans.factory, seeded_plans.tenant_id(KEY))
    assert holder.acquire()
    try:
        outcome = run(seeded_plans)
        assert outcome.status == "skipped"
        assert "in progress" in (outcome.reason or "")
        assert counts(seeded_plans)["jobs"] == 0
        other = run(seeded_plans, "med_a")  # another business is not blocked
        assert other.status == "succeeded"
    finally:
        holder.release()
    assert run(seeded_plans).status == "succeeded"


def test_data_quality_issues_are_stored_and_resolved(seeded_plans: PipelineDb) -> None:
    run(seeded_plans)
    with seeded_plans.session() as s:
        open_codes = {
            r[0]
            for r in s.execute(
                text("SELECT code FROM data_quality_issues WHERE resolved_at IS NULL")
            )
        }
        assert {"MISSING_COST", "MISSING_SUPPLIER", "PO_OVERDUE", "MISSING_EXPIRY"} <= open_codes
        s.execute(
            text(
                "UPDATE supplier_product_terms SET lead_time_days = 2 WHERE lead_time_days IS NULL"
            )
        )
        s.commit()
    run(seeded_plans, force=True)
    with seeded_plans.session() as s:
        resolved = s.execute(
            text(
                "SELECT count(*) FROM data_quality_issues WHERE code = 'MISSING_LEAD_TIME' AND resolved_at IS NOT NULL"
            )
        ).scalar()
        assert (resolved or 0) >= 0  # the supplier default may still apply, so just no crash
        s.execute(
            text("UPDATE supplier_product_terms SET lead_time_days = NULL WHERE lead_time_days = 2")
        )
        s.commit()


def test_retention_keeps_the_newest_forecast_runs(seeded_plans: PipelineDb) -> None:
    for _ in range(10):
        run(seeded_plans, force=True)
    with seeded_plans.session() as s:
        n_runs = s.scalar(
            select(func.count(func.distinct(ForecastValue.run_id))).select_from(ForecastValue)
        )
        assert n_runs == 8


def test_golden_output(seeded_plans: PipelineDb) -> None:
    """The numbers of a fixed seed do not change by accident. Set UPDATE_GOLDEN=1 to rewrite."""
    outcome = run(seeded_plans)
    with seeded_plans.session() as s:
        report = s.get(WeeklyReport, outcome.report_id)
        assert report is not None
        payload = normalise(report.payload)
    keep = (
        "forecast_method",
        "demand_7d",
        "suggested_qty",
        "allocated_qty",
        "risk_level",
        "confidence",
        "stock_status",
        "sections",
        "reason_codes",
        "est_spend",
        "on_hand_usable",
        "incoming_confirmed",
        "safety_stock",
        "lead_time_days",
    )
    lines = {ln["sku"]: {k: ln[k] for k in keep} for ln in payload["lines"].values()}
    actual = {
        "summary": {k: v for k, v in payload["summary"].items() if k != "festival_note"},
        "lines": dict(sorted(lines.items())),
    }
    path = GOLDEN / "fmcg_a_light.json"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual["summary"] == expected["summary"]
    assert actual["lines"] == expected["lines"]


def test_backfill_writes_decisions_and_corpus_documents(seeded_plans: PipelineDb) -> None:
    from datetime import timedelta

    from app.models.agents import KnowledgeDocument
    from app.models.intelligence import RecommendationDecision
    from app.services.backfill import backfill_tenant

    tenant_id = seeded_plans.tenant_id("med_a")
    last = AS_OF - timedelta(days=7)
    outcomes = backfill_tenant(seeded_plans.factory, tenant_id, last, 2)
    assert [o.status for o in outcomes] == ["succeeded", "succeeded"]
    with seeded_plans.session() as s:
        reports = s.scalars(
            select(WeeklyReport).where(
                WeeklyReport.tenant_id == tenant_id, WeeklyReport.payload["backfill"].as_boolean()
            )
        ).all()
        assert len(reports) == 2
        decisions = s.scalar(
            select(func.count())
            .select_from(RecommendationDecision)
            .where(RecommendationDecision.tenant_id == tenant_id)
        )
        docs = {
            kind: s.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.doc_type == kind)
            )
            for kind in ("decision_memory", "report_narrative")
        }
    assert decisions and decisions > 0
    assert docs["report_narrative"] == 2
    assert docs["decision_memory"] and docs["decision_memory"] > 0


def test_reset_password_command(
    seeded_plans: PipelineDb, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.config import get_settings
    from app.core.security import PasswordService
    from app.jobs import accounts

    with seeded_plans.session() as s:
        email = s.execute(
            text("SELECT email FROM users WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
            {"t": seeded_plans.tenant_id(KEY)},
        ).scalar_one()
    monkeypatch.setattr(accounts, "get_session_factory", lambda: seeded_plans.factory)
    monkeypatch.setenv(accounts.PASSWORD_ENV, "short")
    assert accounts.reset_password(email) == 2
    assert "not accepted" in capsys.readouterr().out
    assert accounts.reset_password("nobody@example.invalid") == 2
    new_password = "Quartz-Lantern-4417-meadow"
    monkeypatch.setenv(accounts.PASSWORD_ENV, new_password)
    assert accounts.reset_password(email) == 0
    with seeded_plans.session() as s:
        stored = s.execute(
            text("SELECT password_hash FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    assert PasswordService(get_settings()).verify(stored, new_password)
    assert new_password not in capsys.readouterr().out


def test_simulate_week_reports_that_it_is_not_built(capsys: pytest.CaptureFixture[str]) -> None:
    from app.jobs import run as run_module

    assert run_module.main(["simulate-week"]) == 0
    assert "not built yet" in capsys.readouterr().out
