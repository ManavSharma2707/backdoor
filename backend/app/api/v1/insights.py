"""Dashboard, insights and data quality (`api-spec.md` section 9)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.audit import AuditAction, AuditService
from app.core.db import transaction
from app.core.deps import OwnerCtx, SessionDep, owner_context
from app.core.pagination import Page, PageDep
from app.services.dq_run import run_checks
from app.services.insight_service import InsightService

guard = [Depends(owner_context)]
dashboard = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=guard)
insights = APIRouter(prefix="/insights", tags=["insights"], dependencies=guard)
quality = APIRouter(prefix="/data-quality", tags=["data quality"], dependencies=guard)


class DqIssue(BaseModel):
    id: str
    code: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    message: str
    label: str | None
    fix_hint: str | None
    detected_at: str
    resolved_at: str | None


class DqRunResult(BaseModel):
    inserted: int
    updated: int
    resolved: int


@dashboard.get("/summary", summary="Key numbers and what needs attention")
def dashboard_summary(ctx: OwnerCtx, session: SessionDep) -> dict[str, Any]:
    return InsightService(session, ctx).dashboard_summary()


@dashboard.get("/trends", summary="Weekly sales with festival bands")
def dashboard_trends(
    ctx: OwnerCtx, session: SessionDep, weeks: Annotated[int, Query(ge=2, le=52)] = 12
) -> dict[str, Any]:
    return InsightService(session, ctx).trends(weeks)


@dashboard.get("/activity", summary="Newest bills, orders and deliveries")
def dashboard_activity(
    ctx: OwnerCtx, session: SessionDep, limit: Annotated[int, Query(ge=1, le=30)] = 8
) -> dict[str, Any]:
    return InsightService(session, ctx).activity(limit)


@dashboard.get("/cover-by-category", summary="Days of cover per category")
def cover_by_category(ctx: OwnerCtx, session: SessionDep) -> dict[str, Any]:
    return InsightService(session, ctx).cover_by_category()


@insights.get("/movers", summary="ABC classes, fast, slow and non-moving products")
def movers(
    ctx: OwnerCtx, session: SessionDep, window: Annotated[int, Query(ge=14, le=365)] = 90
) -> dict[str, Any]:
    return InsightService(session, ctx).movers(window)


@insights.get("/forecast-accuracy", summary="Backtest results against the baselines")
def forecast_accuracy(
    ctx: OwnerCtx, session: SessionDep, segment: Annotated[str | None, Query(max_length=60)] = None
) -> dict[str, Any]:
    return InsightService(session, ctx).forecast_accuracy(segment)


@insights.get("/forecast-vs-actual", summary="Forecast and actual sales by week")
def forecast_vs_actual(
    ctx: OwnerCtx,
    session: SessionDep,
    product_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    weeks: Annotated[int, Query(ge=2, le=26)] = 8,
) -> dict[str, Any]:
    return InsightService(session, ctx).forecast_vs_actual(product_id, category_id, weeks)


@insights.get("/festival-effects", summary="Effects learned from festivals and seasons")
def festival_effects(ctx: OwnerCtx, session: SessionDep) -> dict[str, Any]:
    return InsightService(session, ctx).festival_effects()


@insights.get("/suppliers", summary="Supplier scorecards")
def supplier_scorecards(ctx: OwnerCtx, session: SessionDep) -> list[dict[str, Any]]:
    return InsightService(session, ctx).supplier_scorecards()


@insights.get("/expiry-waste", summary="Write offs and returns by reason and month")
def expiry_waste(
    ctx: OwnerCtx, session: SessionDep, months: Annotated[int, Query(ge=1, le=24)] = 6
) -> dict[str, Any]:
    return InsightService(session, ctx).expiry_waste(months)


@quality.get("/issues", response_model=Page[DqIssue], summary="Data quality issues")
def issues(
    ctx: OwnerCtx, session: SessionDep, page: PageDep, resolved: bool = False
) -> Page[DqIssue]:
    rows, total = InsightService(session, ctx).issues(resolved, page.page_size, page.offset)
    return Page[DqIssue](
        items=[DqIssue(**r) for r in rows], total=total, page=page.page, page_size=page.page_size
    )


@quality.post("/run", response_model=DqRunResult, summary="Check the data again")
def run_data_checks(ctx: OwnerCtx, session: SessionDep) -> DqRunResult:
    counts = run_checks(session, ctx.tenant_id)
    with transaction(session):
        AuditService(session).record(
            AuditAction.DQ_RUN,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            meta=ctx.meta,
            entity_type="data_quality",
            after=counts,
        )
    return DqRunResult(**counts)
