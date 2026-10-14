"""Bills, voids, returns and summaries (`api-spec.md` section 5)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.deps import OwnerCtx, SessionDep, SettingsDep, owner_context
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageDep
from app.schemas.sales import (
    ReturnCreate,
    ReturnOut,
    SaleCreate,
    SaleListItem,
    SaleOut,
    SalesSummary,
    SaleStatus,
    VoidRequest,
)
from app.services.sales_service import SalesService

router = APIRouter(prefix="/sales", tags=["sales"], dependencies=[Depends(owner_context)])


@router.post(
    "",
    response_model=SaleOut,
    status_code=201,
    summary="Save a bill",
    responses={
        409: {"description": "Not enough stock, expired batch or bill number already used"},
    },
)
def create_sale(
    body: SaleCreate,
    ctx: OwnerCtx,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    key: IdempotencyKey = None,
) -> dict[str, object]:
    """Allocates first-expired-first-out batches, prices the lines, writes the stock movements.
    Send an `Idempotency-Key` so a retry cannot save the bill twice."""
    return run_idempotent(
        session,
        tenant_id=ctx.tenant_id,
        settings=settings,
        key=key,
        scope="POST /sales",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            SalesService(session, ctx).create(body, idempotency_key=key).model_dump(mode="json")
        ),
    )


@router.get("", response_model=Page[SaleListItem], summary="List bills")
def list_sales(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    start: Annotated[date | None, Query(alias="from", description="First business date")] = None,
    end: Annotated[date | None, Query(alias="to", description="Last business date")] = None,
    q: Annotated[str | None, Query(max_length=40, description="Part of a bill number")] = None,
    status: SaleStatus | None = None,
    sort: Annotated[str | None, Query(description="sold_at, bill_no, total")] = None,
) -> Page[SaleListItem]:
    items, total = SalesService(session, ctx).search(
        page=page, start=start, end=end, q=q, status=status, sort=sort
    )
    return Page[SaleListItem](items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/summary", response_model=SalesSummary, summary="Sales totals for charts")
def sales_summary(
    ctx: OwnerCtx,
    session: SessionDep,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    group: Literal["day", "week"] = "day",
) -> SalesSummary:
    return SalesService(session, ctx).summary(start=start, end=end, group=group)


@router.get("/{sale_id}", response_model=SaleOut, summary="Bill with lines and returns")
def get_sale(sale_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> SaleOut:
    return SalesService(session, ctx).get(sale_id)


@router.post("/{sale_id}/void", response_model=SaleOut, summary="Void a whole bill")
def void_sale(sale_id: uuid.UUID, body: VoidRequest, ctx: OwnerCtx, session: SessionDep) -> SaleOut:
    """Writes reversing movements. The original movements stay in the ledger."""
    return SalesService(session, ctx).void(sale_id, body.reason)


@router.post(
    "/{sale_id}/returns",
    response_model=ReturnOut,
    status_code=201,
    summary="Take goods back against a bill",
    responses={409: {"description": "More than was sold (RETURN_EXCEEDS_SOLD) or bill is void"}},
)
def create_return(
    sale_id: uuid.UUID,
    body: ReturnCreate,
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
        scope=f"POST /sales/{sale_id}/returns",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            SalesService(session, ctx).create_return(sale_id, body).model_dump(mode="json")
        ),
    )
