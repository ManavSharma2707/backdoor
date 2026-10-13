"""Liveness and readiness. No authentication."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.logging import get_logger
from app.jobs.migrate import head_revision
from app.schemas.common import HealthStatus
from app.version import APP_VERSION

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health", summary="Liveness", response_model=HealthStatus, response_model_exclude_none=True
)
def liveness() -> HealthStatus:
    """The process is up. Does not touch the database, so a cold database cannot fail it."""
    return HealthStatus(status="ok", version=APP_VERSION)


@router.get(
    "/health/ready",
    summary="Readiness",
    response_model=HealthStatus,
    response_model_exclude_none=True,
    responses={503: {"model": HealthStatus, "description": "Database down or migrations pending"}},
)
def readiness(response: Response, session: Session = Depends(get_session)) -> HealthStatus:  # noqa: B008
    """The process can reach the database and the schema is at the migration head."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.warning("health.database_unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable", version=APP_VERSION, database="down")

    try:
        current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        session.rollback()
        current = None
    if current is None or current != head_revision():
        log.warning("health.migrations_not_at_head", current=current, head=head_revision())
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        migration = "unknown" if current is None else "behind"
        return HealthStatus(
            status="unavailable", version=APP_VERSION, database="up", migration=migration
        )
    return HealthStatus(status="ok", version=APP_VERSION, database="up", migration="current")
