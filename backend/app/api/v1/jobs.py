"""Jobs and operations (`api-spec.md` section 10).

`POST /jobs/monday-report` is for wake up calls and light runs, authorised by the job token. The
scheduled full run is the script entry point, never this endpoint.
"""

import hmac
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.api.v1.reports import session_factory
from app.core.clock import today_ist
from app.core.deps import (
    ROLE_RANK,
    OwnerCtx,
    SessionDep,
    SettingsDep,
    bearer_scheme,
    get_current_user,
)
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.pagination import Page, PageDep
from app.schemas.reports import JobRunOut
from app.services import jobs as job_service
from app.services import pipeline

router = APIRouter(prefix="/jobs", tags=["jobs"])
job_token_scheme = APIKeyHeader(name="X-Job-Token", scheme_name="JobToken", auto_error=False)
JobToken = Annotated[str | None, Security(job_token_scheme)]


class JobsAccepted(BaseModel):
    job_run_ids: list[uuid.UUID]
    skipped: list[str]


def require_job_token(supplied: str | None, expected: str) -> None:
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise AppError(ErrorCode.UNAUTHENTICATED)


def run_all(
    factory,  # type: ignore[no-untyped-def]
    work: list[tuple[uuid.UUID, uuid.UUID]],
    week,  # type: ignore[no-untyped-def]
    profile: str,
    force: bool,
) -> None:
    """Background task: the runs go one after the other, each with its own job row."""
    for tenant_id, job_id in work:
        pipeline.run_pipeline(factory, tenant_id, week, profile, force=force, job_id=job_id)


@router.post(
    "/monday-report",
    status_code=202,
    response_model=JobsAccepted,
    summary="Start the Monday report for one business or all (job token)",
)
def monday_report(
    request: Request,
    settings: SettingsDep,
    background: BackgroundTasks,
    tenant: Annotated[str, Query(max_length=60, description="Business slug, or all")] = "all",
    profile: Literal["light", "full"] = "light",
    force: bool = False,
    x_job_token: JobToken = None,
) -> JobsAccepted:
    require_job_token(x_job_token, settings.job_token.get_secret_value())
    factory = session_factory(request)
    week = pipeline.monday_of(today_ist())
    work: list[tuple[uuid.UUID, uuid.UUID]] = []
    skipped: list[str] = []
    for tenant_id, slug in pipeline.tenant_ids(factory, tenant):
        job_id, reason = pipeline.start_job(factory, tenant_id, week, force=force, profile=profile)
        if job_id is None:
            skipped.append(f"{slug}: {reason}")
        else:
            work.append((tenant_id, job_id))
    if not work and not skipped:
        raise AppError(ErrorCode.NOT_FOUND, "We could not find that business.")
    background.add_task(run_all, factory, work, week, profile, force)
    return JobsAccepted(job_run_ids=[job for _, job in work], skipped=skipped)


@router.get("/runs", response_model=Page[JobRunOut], summary="Recent runs of your business")
def list_runs(ctx: OwnerCtx, session: SessionDep, page: PageDep) -> Page[JobRunOut]:
    items, total = job_service.list_jobs(session, ctx.tenant_id, page)
    return Page[JobRunOut](items=items, total=total, page=page.page, page_size=page.page_size)


def job_or_owner(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_job_token: JobToken = None,
) -> uuid.UUID | None:
    """The tenant a caller is limited to, or None for a valid job token (any business)."""
    if x_job_token is not None:
        require_job_token(x_job_token, settings.job_token.get_secret_value())
        return None
    user = get_current_user(credentials, session, settings)
    if ROLE_RANK.get(user.role, 0) < ROLE_RANK["owner"]:
        raise AppError(ErrorCode.FORBIDDEN)
    return user.tenant_id


@router.get("/runs/{run_id}", response_model=JobRunOut, summary="One run (job token or owner)")
def get_run(
    run_id: uuid.UUID,
    session: SessionDep,
    scope: Annotated[uuid.UUID | None, Depends(job_or_owner)],
) -> JobRunOut:
    return job_service.job_out(session, scope, run_id)
