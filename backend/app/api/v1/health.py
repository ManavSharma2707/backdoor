"""Liveness and readiness. No authentication."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.logging import get_logger
from app.schemas.common import HealthStatus

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness", response_model=HealthStatus)
def liveness() -> HealthStatus:
    """The process is up. Does not touch the database, so a cold database cannot fail it."""
    return HealthStatus(status="ok")


@router.get(
    "/health/ready",
    summary="Readiness",
    response_model=HealthStatus,
    responses={503: {"model": HealthStatus, "description": "The database is unreachable"}},
)
def readiness(response: Response, session: Session = Depends(get_session)) -> HealthStatus:  # noqa: B008
    """The process can reach the database."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.warning("health.database_unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable", database="down")
    return HealthStatus(status="ok", database="up")
