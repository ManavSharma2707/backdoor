"""Stock, batches, movements, adjustments, counts, stockouts, reconciliation, supplier returns
(`api-spec.md` section 7)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.deps import OwnerCtx, SessionDep, SettingsDep, owner_context
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageDep
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentOut,
    BatchRow,
    CountCreate,
    CountLinesPatch,
    CountListItem,
    CountOut,
    MovementRow,
    MovementType,
    ProductStockOut,
    ReconcileOut,
    StockoutCreate,
    StockoutOut,
    StockoutPatch,
    StockRow,
    StockStatus,
    SupplierReturnCreate,
    SupplierReturnOut,
    WriteOffRequest,
)
from app.services.inventory_service import InventoryService

guard = [Depends(owner_context)]
inventory = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=guard)
product_stock = APIRouter(prefix="/products", tags=["inventory"], dependencies=guard)
supplier_returns = APIRouter(prefix="/suppliers", tags=["inventory"], dependencies=guard)

Range = Annotated[date | None, Query()]


@inventory.get("/stock", response_model=Page[StockRow], summary="Stock levels")
def stock_levels(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=80)] = None,
    category_id: uuid.UUID | None = None,
    status: StockStatus | None = None,
    risk: Annotated[
        Literal["critical", "high", "medium", "low", "none"] | None,
        Query(description="Risk level from the latest plan"),
    ] = None,
    include_inactive: bool = False,
    sort: Annotated[str | None, Query(description="name, sku, on_hand, value")] = None,
) -> Page[StockRow]:
    items, total = InventoryService(session, ctx).stock_levels(
        page=page,
        q=q,
        category_id=category_id,
        status=status,
        risk=risk,
        include_inactive=include_inactive,
        sort=sort,
    )
    return Page[StockRow](items=items, total=total, page=page.page, page_size=page.page_size)


@inventory.get("/batches", response_model=Page[BatchRow], summary="Batches with days to expiry")
def batches(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    expired: bool | None = None,
    product_id: uuid.UUID | None = None,
    status: Literal["active", "quarantined", "expired", "closed"] | None = None,
    include_empty: bool = False,
) -> Page[BatchRow]:
    """Earliest expiry first. Batches with nothing left are left out unless asked for."""
    items, total = InventoryService(session, ctx).batch_rows(
        page=page,
        expiring_within_days=expiring_within_days,
        expired=expired,
        product_id=product_id,
        status=status,
        include_empty=include_empty,
    )
    return Page[BatchRow](items=items, total=total, page=page.page, page_size=page.page_size)


@inventory.get("/movements", response_model=Page[MovementRow], summary="The stock ledger")
def movements(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    product_id: uuid.UUID | None = None,
    type: MovementType | None = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> Page[MovementRow]:
    items, total = InventoryService(session, ctx).movement_rows(
        page=page, product_id=product_id, movement_type=type, start=start, end=end
    )
    return Page[MovementRow](items=items, total=total, page=page.page, page_size=page.page_size)


@inventory.post(
    "/adjustments",
    response_model=AdjustmentOut,
    status_code=201,
    summary="Add or remove stock with a reason",
    responses={409: {"description": "Not enough stock to remove (INSUFFICIENT_STOCK)"}},
)
def create_adjustment(
    body: AdjustmentCreate,
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
        scope="POST /inventory/adjustments",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            InventoryService(session, ctx).adjust(body, idempotency_key=key).model_dump(mode="json")
        ),
    )


@inventory.post(
    "/batches/{batch_id}/write-off",
    response_model=AdjustmentOut,
    status_code=201,
    summary="Write off what is left of a batch",
)
def write_off_batch(
    batch_id: uuid.UUID, body: WriteOffRequest, ctx: OwnerCtx, session: SessionDep
) -> AdjustmentOut:
    """For an expired batch, or a damaged one. The batch is closed afterwards."""
    return InventoryService(session, ctx).write_off(batch_id, body)


@inventory.post("/counts", response_model=CountOut, status_code=201, summary="Start a stock count")
def create_count(body: CountCreate, ctx: OwnerCtx, session: SessionDep) -> CountOut:
    """Takes a snapshot of the system quantities for all products, a category or a selection."""
    return InventoryService(session, ctx).create_count(body)


@inventory.get("/counts", response_model=Page[CountListItem], summary="List stock counts")
def list_counts(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    status: Literal["draft", "posted", "void"] | None = None,
) -> Page[CountListItem]:
    items, total = InventoryService(session, ctx).list_counts(page=page, status=status)
    return Page[CountListItem](items=items, total=total, page=page.page, page_size=page.page_size)


@inventory.get("/counts/{count_id}", response_model=CountOut, summary="Count sheet")
def get_count(count_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> CountOut:
    return InventoryService(session, ctx).get_count(count_id)


@inventory.patch(
    "/counts/{count_id}/lines", response_model=CountOut, summary="Enter counted quantities"
)
def enter_counted_quantities(
    count_id: uuid.UUID, body: CountLinesPatch, ctx: OwnerCtx, session: SessionDep
) -> CountOut:
    return InventoryService(session, ctx).enter_counts(count_id, body)


@inventory.post("/counts/{count_id}/post", response_model=CountOut, summary="Post the differences")
def post_count(count_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> CountOut:
    """Writes one `count_correction` movement per line that differs. Uncounted lines are left."""
    return InventoryService(session, ctx).post_count(count_id)


@inventory.get("/stockouts", response_model=Page[StockoutOut], summary="Out of stock periods")
def list_stockouts(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    product_id: uuid.UUID | None = None,
    source: Literal["recorded", "inferred"] | None = None,
    open_only: bool = False,
) -> Page[StockoutOut]:
    items, total = InventoryService(session, ctx).list_stockouts(
        page=page, product_id=product_id, source=source, open_only=open_only
    )
    return Page[StockoutOut](items=items, total=total, page=page.page, page_size=page.page_size)


@inventory.post(
    "/stockouts",
    response_model=StockoutOut,
    status_code=201,
    summary="Record an out of stock period",
)
def record_stockout(body: StockoutCreate, ctx: OwnerCtx, session: SessionDep) -> StockoutOut:
    return InventoryService(session, ctx).record_stockout(body)


@inventory.patch(
    "/stockouts/{interval_id}", response_model=StockoutOut, summary="End or annotate a period"
)
def update_stockout(
    interval_id: uuid.UUID, body: StockoutPatch, ctx: OwnerCtx, session: SessionDep
) -> StockoutOut:
    return InventoryService(session, ctx).update_stockout(interval_id, body)


@inventory.post(
    "/reconcile", response_model=ReconcileOut, summary="Check balances against the ledger"
)
def reconcile(ctx: OwnerCtx, session: SessionDep) -> ReconcileOut:
    """Runs the reconciliation queries. An empty list of mismatches means the books agree."""
    return InventoryService(session, ctx).reconcile()


@product_stock.get("/{product_id}/stock", response_model=ProductStockOut, summary="Stock per batch")
def get_product_stock(product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ProductStockOut:
    return InventoryService(session, ctx).product_stock(product_id)


@supplier_returns.post(
    "/{supplier_id}/returns",
    response_model=SupplierReturnOut,
    status_code=201,
    summary="Send stock back to a supplier",
    responses={409: {"description": "Against the supplier's returns policy, or not enough stock"}},
)
def return_to_supplier(
    supplier_id: uuid.UUID,
    body: SupplierReturnCreate,
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
        scope=f"POST /suppliers/{supplier_id}/returns",
        body=body,
        response=response,
        status_code=201,
        build=lambda: (
            InventoryService(session, ctx)
            .supplier_return(supplier_id, body)
            .model_dump(mode="json")
        ),
    )
