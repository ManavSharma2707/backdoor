"""Helpers shared by the API tests that need stock, batches and bills."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.models.catalogue import Product
from app.models.inventory import InventoryMovement, ProductBatch, StockBalance
from app.models.tenancy import Tenant, User
from app.services.ledger import LedgerService, MovementEntry
from tests import factories

D = Decimal
API = "/api/v1"


def stock_up(
    db: Session,
    tenant: Tenant,
    user: User,
    product: Product,
    quantity: str,
    *,
    batch: ProductBatch | None = None,
    cost: str = "5.0000",
) -> None:
    """Put stock on the shelf through the ledger, the way a receipt would."""
    LedgerService(db, tenant.id, user.id).post(
        [
            MovementEntry(
                product_id=product.id,
                batch_id=batch.id if batch else None,
                movement_type="receipt",
                quantity_delta=D(quantity),
                source_type="receipt",
                source_id=f"test-{uuid.uuid4().hex[:8]}",
                unit_cost=D(cost),
            )
        ]
    )


def tracked_product(db: Session, tenant: Tenant, **overrides: Any) -> Product:
    return factories.make_product(
        db, tenant, is_batch_tracked=True, shelf_life_days=365, **overrides
    )


def make_batch_with_stock(
    db: Session,
    tenant: Tenant,
    user: User,
    product: Product,
    *,
    days_to_expiry: int,
    quantity: str,
    batch_no: str | None = None,
    status: str = "active",
    cost: str = "5.0000",
) -> ProductBatch:
    batch = factories.make_batch(
        db,
        tenant,
        product,
        batch_no=batch_no or f"B{factories.short_id()}",
        expiry_date=today_ist() + timedelta(days=days_to_expiry),
        unit_cost=D(cost),
        initial_qty=D(quantity),
        status=status,
    )
    stock_up(db, tenant, user, product, quantity, batch=batch, cost=cost)
    return batch


def on_hand(db: Session, product: Product, batch: ProductBatch | None = None) -> Decimal:
    value = db.execute(
        select(func.coalesce(func.sum(StockBalance.on_hand), 0)).where(
            StockBalance.product_id == product.id,
            True if batch is None else StockBalance.batch_id == batch.id,
        )
    ).scalar_one()
    return Decimal(value)


def movement_count(db: Session, tenant: Tenant, movement_type: str | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(InventoryMovement)
        .where(InventoryMovement.tenant_id == tenant.id)
    )
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    return int(db.execute(stmt).scalar_one())


def sale_payload(*lines: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"payment_mode": "cash", "lines": list(lines)}
    payload.update(overrides)
    return payload


def line(product: Product, quantity: str = "1", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"product_id": str(product.id), "quantity": quantity}
    body.update(overrides)
    return body


def post_sale(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any], **extra: str
) -> Any:
    return client.post(f"{API}/sales", headers={**headers, **extra}, json=payload)


def today_iso() -> str:
    return today_ist().isoformat()


def days_ago(days: int) -> date:
    return today_ist() - timedelta(days=days)
