"""What if runs (`engine-spec.md` section 15, "Overrides"). They never write plan rows.

A scenario re-plans a stored report with changes: another budget, a longer delivery time, a late
supplier, a different service level, a demand multiplier, products left out or forced in. It
reuses the stored forecasts of that report and reads the stock as it stood at its data cutoff, so
a result differs from the stored plan only by the change that was asked for.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import TenantContext
from app.engine.plan import Line, Overrides, PlanResult, plan_metrics
from app.schemas.reports import ScenarioIn, ScenarioOut
from app.services.plan_compute import ComputeResult, compute_plan
from app.services.report_service import ReportService

MAX_CHANGED_LINES = 60


def overrides_from(body: ScenarioIn) -> Overrides:
    return Overrides(
        weekly_budget=None if body.clear_budget else body.weekly_budget,
        override_budget=body.clear_budget or body.weekly_budget is not None,
        service_level=body.service_level,
        review_period_days=body.review_period_days,
        lead_time_delta_by_supplier={
            str(k): v for k, v in body.lead_time_delta_by_supplier.items()
        },
        supplier_delay_days={str(k): v for k, v in body.supplier_delay_days.items()},
        demand_multiplier=body.demand_multiplier,
        excluded_product_ids=frozenset(str(i) for i in body.excluded_product_ids),
        forced_include_ids=frozenset(str(i) for i in body.forced_include_ids),
    )


def _plain(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in metrics.items()}


def _brief(line: Line) -> dict[str, Any]:
    return {
        "sku": line.product.sku,
        "name": line.product.name,
        "allocated_qty": line.allocated_qty,
        "suggested_qty": line.suggested_qty,
        "risk_level": line.risk_level,
        "est_spend": None if line.est_spend is None else str(line.est_spend),
    }


def changed_lines(base: PlanResult, scenario: PlanResult) -> list[dict[str, Any]]:
    before = base.by_key
    out: list[tuple[float, dict[str, Any]]] = []
    for key, ln in scenario.by_key.items():
        old = before.get(key)
        if old is None:
            continue
        if (old.allocated_qty, old.suggested_qty, old.risk_level) != (
            ln.allocated_qty,
            ln.suggested_qty,
            ln.risk_level,
        ):
            delta = abs(ln.allocated_qty - old.allocated_qty)
            out.append((delta, {"base": _brief(old), "scenario": _brief(ln)}))
    for key, old in before.items():
        if key not in scenario.by_key:
            out.append((old.allocated_qty, {"base": _brief(old), "scenario": None}))
    out.sort(key=lambda item: -item[0])
    return [row for _, row in out[:MAX_CHANGED_LINES]]


class ScenarioService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def _compute(
        self, report_week: Any, forecast_run: uuid.UUID, overrides: Overrides
    ) -> ComputeResult:
        return compute_plan(
            self.session,
            self.ctx.tenant_id,
            report_week,
            "light",
            overrides=overrides,
            live=False,
            forecast_run_id=forecast_run,
        )

    def run(self, report_id: uuid.UUID, body: ScenarioIn) -> ScenarioOut:
        report = ReportService(self.session, self.ctx).ready_report(report_id)
        overrides = overrides_from(body)
        base = self._compute(report.week_start, report.forecast_run_id, Overrides())
        scenario = self._compute(report.week_start, report.forecast_run_id, overrides)
        return ScenarioOut(
            base=_plain(plan_metrics(base.plan)),
            scenario=_plain(plan_metrics(scenario.plan)),
            changes=body.model_dump(mode="json", exclude_defaults=True),
            lines_changed=changed_lines(base.plan, scenario.plan),
            note="A what if run. Nothing was saved and the plan has not changed.",
        )
