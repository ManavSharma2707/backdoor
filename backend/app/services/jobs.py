"""Job runs as the API shows them."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.pagination import PageParams
from app.models.ops import JobRun
from app.schemas.reports import JobRunOut


def to_out(row: JobRun) -> JobRunOut:
    return JobRunOut(
        id=row.id,
        job_name=row.job_name,
        run_key=row.run_key,
        status=row.status,
        attempts=row.attempts,
        started_at=row.started_at,
        finished_at=row.finished_at,
        result=row.result,
        error=row.error,
    )


def job_out(session: Session, tenant_id: uuid.UUID | None, job_id: uuid.UUID) -> JobRunOut:
    """One run. With a tenant id the run must belong to it, a job token may see any."""
    stmt = select(JobRun).where(JobRun.id == job_id)
    if tenant_id is not None:
        stmt = stmt.where(JobRun.tenant_id == tenant_id)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "We could not find that job.")
    return to_out(row)


def list_jobs(
    session: Session, tenant_id: uuid.UUID, params: PageParams
) -> tuple[list[JobRunOut], int]:
    total = (
        session.scalar(
            select(func.count()).select_from(JobRun).where(JobRun.tenant_id == tenant_id)
        )
        or 0
    )
    rows = (
        session.execute(
            select(JobRun)
            .where(JobRun.tenant_id == tenant_id)
            .order_by(JobRun.started_at.desc())
            .limit(params.page_size)
            .offset(params.offset)
        )
        .scalars()
        .all()
    )
    return [to_out(r) for r in rows], int(total)
