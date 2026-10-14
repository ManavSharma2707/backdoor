"""Reports and decisions (`api-spec.md` section 8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.core.audit import AuditAction, AuditService
from app.core.clock import today_ist
from app.core.db import get_session_factory, transaction
from app.core.deps import OwnerCtx, SessionDep, SettingsDep, owner_context
from app.core.errors import AppError
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.messages import ErrorCode
from app.core.pagination import Page, PageDep
from app.schemas.reports import (
    BulkDecisionIn,
    BulkDecisionResult,
    ConfidenceFilter,
    DecisionFilter,
    DecisionIn,
    DecisionResult,
    ExportFormat,
    ExportKind,
    GenerateIn,
    JobRunOut,
    LineDetail,
    NoteIn,
    NoteOut,
    PoDraftResult,
    ReportLineOut,
    ReportListItem,
    ReportOut,
    RiskFilter,
    ScenarioIn,
    ScenarioOut,
    Section,
)
from app.services import pipeline
from app.services.common import invalid
from app.services.decision_service import DecisionService
from app.services.report_service import ReportService
from app.services.scenario import ScenarioService

guard = [Depends(owner_context)]
reports = APIRouter(prefix="/reports", tags=["reports"], dependencies=guard)
report_lines = APIRouter(prefix="/report-lines", tags=["reports"], dependencies=guard)

NOT_READY = {409: {"description": "The plan is not ready (REPORT_NOT_READY) or was replaced"}}


def session_factory(request: Request):  # type: ignore[no-untyped-def]
    """The factory background jobs use. Tests put their own on `app.state`."""
    return getattr(request.app.state, "session_factory", None) or get_session_factory()


@reports.get("", response_model=Page[ReportListItem], summary="List weekly plans")
def list_reports(ctx: OwnerCtx, session: SessionDep, page: PageDep) -> Page[ReportListItem]:
    items, total = ReportService(session, ctx).list_reports(page)
    return Page[ReportListItem](items=items, total=total, page=page.page, page_size=page.page_size)


@reports.get("/latest", response_model=ReportOut, summary="The current plan")
def latest_report(ctx: OwnerCtx, session: SessionDep) -> ReportOut:
    service = ReportService(session, ctx)
    return service.get(service.latest().id)


@reports.post(
    "/generate",
    status_code=202,
    response_model=JobRunOut,
    summary="Generate the plan for a week",
    responses={409: {"description": "A plan for that week exists (use force) or one is running"}},
)
def generate_report(
    body: GenerateIn,
    ctx: OwnerCtx,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> JobRunOut:
    """Runs the light profile in the background. Poll `GET /jobs/runs/{id}` for the result."""
    week = body.week_start or pipeline.monday_of(today_ist())
    if week.weekday() != 0:
        raise invalid("week_start", "must be a Monday")
    if week > pipeline.monday_of(today_ist()):
        raise invalid("week_start", "cannot be in the future")
    factory = session_factory(request)
    probe = pipeline.TenantLock(factory, ctx.tenant_id)
    free = probe.acquire()
    probe.release()
    if not free:
        raise AppError(
            ErrorCode.CONFLICT, "A plan is being prepared right now. Check back in a minute."
        )
    job_id, reason = pipeline.start_job(
        factory, ctx.tenant_id, week, force=body.force, profile="light"
    )
    if job_id is None:
        raise AppError(ErrorCode.CONFLICT, f"{reason} Use force to create a new version of it.")
    with transaction(session):
        AuditService(session).record(
            AuditAction.REPORT_GENERATE,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            meta=ctx.meta,
            entity_type="job_run",
            entity_id=job_id,
            after={"week_start": week, "force": body.force},
        )
    background.add_task(
        pipeline.run_pipeline,
        factory,
        ctx.tenant_id,
        week,
        "light",
        force=body.force,
        job_id=job_id,
    )
    from app.services.jobs import job_out

    return job_out(session, ctx.tenant_id, job_id)


@reports.get(
    "/{report_id}",
    response_model=ReportOut,
    summary="A plan with its headline numbers",
    responses=NOT_READY,
)
def get_report(report_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ReportOut:
    return ReportService(session, ctx).get(report_id)


@reports.get(
    "/{report_id}/lines",
    response_model=Page[ReportLineOut],
    summary="Lines of a plan",
    responses=NOT_READY,
)
def list_lines(
    report_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    section: Section | None = None,
    supplier_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    risk: RiskFilter | None = None,
    confidence: ConfidenceFilter | None = None,
    decision: DecisionFilter | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    sort: Annotated[
        str | None,
        Query(description="name, sku, risk, spend, supplier, suggested, cover, priority"),
    ] = None,
) -> Page[ReportLineOut]:
    items, total = ReportService(session, ctx).lines(
        report_id,
        page,
        section=section,
        supplier_id=supplier_id,
        category_id=category_id,
        risk=risk,
        confidence=confidence,
        decision=decision,
        q=q,
        sort=sort,
    )
    return Page[ReportLineOut](items=items, total=total, page=page.page, page_size=page.page_size)


@reports.get(
    "/{report_id}/lines/{line_id}",
    response_model=LineDetail,
    summary="One line in full",
    responses=NOT_READY,
)
def line_detail(
    report_id: uuid.UUID, line_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep
) -> LineDetail:
    return ReportService(session, ctx).line_detail(report_id, line_id)


@reports.post(
    "/{report_id}/decisions/bulk",
    response_model=BulkDecisionResult,
    summary="Approve or reject several lines",
)
def bulk_decisions(
    report_id: uuid.UUID, body: BulkDecisionIn, ctx: OwnerCtx, session: SessionDep
) -> BulkDecisionResult:
    return DecisionService(session, ctx).bulk(report_id, body)


@reports.post(
    "/{report_id}/purchase-orders",
    status_code=201,
    response_model=PoDraftResult,
    summary="Create draft purchase orders from approved lines",
    responses={
        409: {"description": "A line needs a supplier or a price (MISSING_SUPPLIER_OR_COST)"}
    },
)
def create_purchase_orders(
    report_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    key: IdempotencyKey = None,
) -> dict[str, object]:
    return run_idempotent(
        session,
        tenant_id=ctx.tenant_id,
        settings=settings,
        key=key,
        scope=f"POST /reports/{report_id}/purchase-orders",
        body=None,
        response=response,
        status_code=201,
        build=lambda: (
            DecisionService(session, ctx).create_purchase_orders(report_id).model_dump(mode="json")
        ),
    )


@reports.get("/{report_id}/notes", response_model=list[NoteOut], summary="Notes on a plan")
def list_notes(report_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> list[NoteOut]:
    return ReportService(session, ctx).notes(report_id)


@reports.post("/{report_id}/notes", status_code=201, response_model=NoteOut, summary="Add a note")
def add_note(report_id: uuid.UUID, body: NoteIn, ctx: OwnerCtx, session: SessionDep) -> NoteOut:
    return DecisionService(session, ctx).add_note(report_id, body)


@reports.get(
    "/{report_id}/export",
    summary="Download the plan as PDF, Excel or CSV",
    responses={200: {"description": "The file", "content": {"application/octet-stream": {}}}},
)
def export_report(
    report_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    format: Annotated[ExportFormat, Query(description="pdf, xlsx or csv")],
    section: Section | None = None,
    supplier_id: uuid.UUID | None = None,
    kind: ExportKind = "purchase_list",
) -> Response:
    """Built from the saved plan, so it always matches the screen. Authorised by the bearer
    token: the browser downloads it with `fetch` and saves the blob, there is no public link."""
    from app.services.export.service import export_report as build

    file = build(
        session, ctx, report_id, fmt=format, kind=kind, section=section, supplier_id=supplier_id
    )
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file.filename}"',
            "Cache-Control": "no-store",
        },
    )


@reports.post(
    "/{report_id}/scenario",
    response_model=ScenarioOut,
    summary="What if: re-plan with changes, nothing is saved",
)
def run_scenario(
    report_id: uuid.UUID, body: ScenarioIn, ctx: OwnerCtx, session: SessionDep
) -> ScenarioOut:
    """Uses the stored forecasts and the stock of that plan. Never writes plan rows."""
    return ScenarioService(session, ctx).run(report_id, body)


@report_lines.put(
    "/{line_id}/decision",
    response_model=DecisionResult,
    summary="Approve, edit or reject a line",
    responses=NOT_READY,
)
def decide_line(
    line_id: uuid.UUID, body: DecisionIn, ctx: OwnerCtx, session: SessionDep
) -> DecisionResult:
    """An edit needs `final_qty` in whole packs unless the reason is `other`."""
    return DecisionService(session, ctx).decide(line_id, body)
