"""Festival and season calendar (`api-spec.md` section 3). Events are shared reference data."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import SessionDep, owner_context
from app.models.reference import CalendarEvent

router = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(owner_context)])


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_key: str
    name: str
    kind: str
    start_date: date
    end_date: date
    pre_window_days: int
    post_window_days: int
    delivery_delay_days: int
    is_verified: bool
    is_active: bool


@router.get("/events", response_model=list[CalendarEventOut], summary="Festivals and seasons")
def list_events(
    session: SessionDep,
    start: Annotated[date | None, Query(alias="from", description="Ends on or after")] = None,
    end: Annotated[date | None, Query(alias="to", description="Starts on or before")] = None,
    kind: Literal["festival", "season", "holiday"] | None = None,
) -> list[CalendarEventOut]:
    stmt = select(CalendarEvent).where(CalendarEvent.is_active.is_(True))
    if start is not None:
        stmt = stmt.where(CalendarEvent.end_date >= start)
    if end is not None:
        stmt = stmt.where(CalendarEvent.start_date <= end)
    if kind is not None:
        stmt = stmt.where(CalendarEvent.kind == kind)
    rows = session.scalars(stmt.order_by(CalendarEvent.start_date, CalendarEvent.name)).all()
    return [
        CalendarEventOut(
            id=str(row.id),
            event_key=row.event_key,
            name=row.name,
            kind=row.kind,
            start_date=row.start_date,
            end_date=row.end_date,
            pre_window_days=row.pre_window_days,
            post_window_days=row.post_window_days,
            delivery_delay_days=row.delivery_delay_days,
            is_verified=row.is_verified,
            is_active=row.is_active,
        )
        for row in rows
    ]
