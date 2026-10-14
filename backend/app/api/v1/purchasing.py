"""Purchase orders and goods receipts (`api-spec.md` section 6)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response

from app.core.deps import OwnerCtx, SessionDep, SettingsDep, owner_context
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageDep
from app.schemas.purchasing import (
    DirectReceiptCreate,
    POCancel,
    POCreate,
    POListItem,
    POOut,
    POPatch,
    PoStatus,
    ReceiptCreate,
    ReceiptListItem,
    ReceiptOut,
)
from app.services.purchasing_service import PurchasingService

guard = [Depends(owner_context)]
orders = APIRouter(prefix="/purchase-orders", tags=["purchasing"], dependencies=guard)
receipts = APIRouter(prefix="/receipts", tags=["purchasing"], dependencies=guard)

STATE_RESPONSE = {
    409: {"description": "The order is not in a state that allows this (PO_STATE_INVALID)"}
}


@orders.get("", response_model=Page[POListItem], summary="List purchase orders")
def list_orders(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    status: PoStatus | None = None,
    supplier_id: uuid.UUID | None = None,
    overdue: Annotated[
        bool | None, Query(description="Sent orders past their expected date")
    ] = None,
    q: Annotated[str | None, Query(max_length=40, description="Part of the order number")] = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    sort: Annotated[
        str | None, Query(description="order_date, expected_date, po_number, value")
    ] = None,
) -> Page[POListItem]:
    items, total = PurchasingService(session, ctx).search(
        page=page,
        status=status,
        supplier_id=supplier_id,
        overdue=overdue,
        q=q,
        start=start,
        end=end,
        sort=sort,
    )
    return Page[POListItem](items=items, total=total, page=page.page, page_size=page.page_size)


@orders.post(
    "",
    response_model=POOut,
    status_code=201,
    summary="Create a draft purchase order",
    responses={409: {"description": "A product has no price (MISSING_SUPPLIER_OR_COST)"}},
)
def create_order(body: POCreate, ctx: OwnerCtx, session: SessionDep) -> POOut:
    """Cost, pack size and expected date default from the supplier's terms."""
    return PurchasingService(session, ctx).create(body)


@orders.get("/{po_id}", response_model=POOut, summary="Order with lines, receipts and timeline")
def get_order(po_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> POOut:
    return PurchasingService(session, ctx).get(po_id)


@orders.patch(
    "/{po_id}", response_model=POOut, summary="Edit a draft order", responses=STATE_RESPONSE
)
def update_order(po_id: uuid.UUID, body: POPatch, ctx: OwnerCtx, session: SessionDep) -> POOut:
    return PurchasingService(session, ctx).update(po_id, body)


@orders.post(
    "/{po_id}/send", response_model=POOut, summary="Mark as sent", responses=STATE_RESPONSE
)
def send_order(po_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> POOut:
    return PurchasingService(session, ctx).send(po_id)


@orders.post(
    "/{po_id}/cancel", response_model=POOut, summary="Cancel an order", responses=STATE_RESPONSE
)
def cancel_order(
    po_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    body: Annotated[POCancel | None, Body()] = None,
) -> POOut:
    return PurchasingService(session, ctx).cancel(po_id, body.reason if body else None)


@orders.post(
    "/{po_id}/close", response_model=POOut, summary="Close an order", responses=STATE_RESPONSE
)
def close_order(po_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> POOut:
    """Ends an order that will not arrive in full. Whatever was received stays in stock."""
    return PurchasingService(session, ctx).close(po_id)


@orders.post(
    "/{po_id}/receipts",
    response_model=ReceiptOut,
    status_code=201,
    summary="Receive goods against an order",
    responses={
        409: {"description": "More than the open quantity (RECEIPT_EXCEEDS_ORDER) or wrong state"}
    },
)
def receive_goods(
    po_id: uuid.UUID,
    body: ReceiptCreate,
    ctx: OwnerCtx,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    key: IdempotencyKey = None,
) -> dict[str, object]:
    """Creates batches for batch tracked products, adds stock and updates the order status."""
    return run_idempotent(
        session,
        tenant_id=ctx.tenant_id,
        settings=settings,
        key=key,
        scope=f"POST /purchase-orders/{po_id}/receipts",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            PurchasingService(session, ctx)
            .receive(po_id, body, idempotency_key=key)
            .model_dump(mode="json")
        ),
    )


@receipts.post(
    "",
    response_model=ReceiptOut,
    status_code=201,
    summary="Receive goods without an order (exception)",
)
def receive_without_order(
    body: DirectReceiptCreate,
    ctx: OwnerCtx,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    key: IdempotencyKey = None,
) -> dict[str, object]:
    """Needs `is_exception: true` and a note."""
    return run_idempotent(
        session,
        tenant_id=ctx.tenant_id,
        settings=settings,
        key=key,
        scope="POST /receipts",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            PurchasingService(session, ctx)
            .receive_direct(body, idempotency_key=key)
            .model_dump(mode="json")
        ),
    )


@receipts.get("", response_model=Page[ReceiptListItem], summary="List goods receipts")
def list_receipts(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    supplier_id: uuid.UUID | None = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query(max_length=40, description="Receipt or invoice number")] = None,
) -> Page[ReceiptListItem]:
    items, total = PurchasingService(session, ctx).search_receipts(
        page=page, supplier_id=supplier_id, start=start, end=end, q=q
    )
    return Page[ReceiptListItem](items=items, total=total, page=page.page, page_size=page.page_size)


@receipts.get("/{receipt_id}", response_model=ReceiptOut, summary="Receipt detail")
def get_receipt(receipt_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ReceiptOut:
    return PurchasingService(session, ctx).get_receipt(receipt_id)
