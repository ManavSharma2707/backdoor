"""Plain factory functions for tests. Each flushes so ids and defaults are available."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalogue import Category, Product
from app.models.intelligence import (
    ForecastRun,
    RecommendationDecision,
    RecommendationLine,
    RecommendationRun,
    WeeklyReport,
)
from app.models.inventory import InventoryMovement, ProductBatch, StockBalance
from app.models.purchasing import PurchaseOrder, PurchaseOrderLine
from app.models.reference import ModelVersion, TaxRate
from app.models.sales import Sale, SaleLine
from app.models.suppliers import Supplier, SupplierProductTerm
from app.models.tenancy import Tenant, User

BUSINESS_DATE = date(2026, 10, 12)
SOME_INSTANT = datetime(2026, 10, 12, 4, 30, tzinfo=UTC)
PLACEHOLDER_HASH = "not-a-real-hash"  # Auth arrives in Prompt 2, tests here never log in.


def short_id() -> str:
    return uuid.uuid4().hex[:8]


def _save[T](db: Session, obj: T) -> T:
    db.add(obj)
    db.flush()
    return obj


def tax_rate(db: Session, code: str = "GST5") -> TaxRate:
    return db.execute(select(TaxRate).where(TaxRate.code == code)).scalar_one()


def make_tenant(db: Session, **overrides: Any) -> Tenant:
    values: dict[str, Any] = {
        "slug": f"tenant-{short_id()}",
        "name": "Test Traders",
        "business_type": "fmcg",
        "is_synthetic": True,
    }
    return _save(db, Tenant(**{**values, **overrides}))


def make_user(db: Session, tenant: Tenant, **overrides: Any) -> User:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "email": f"owner-{short_id()}@example.com",
        "password_hash": PLACEHOLDER_HASH,
        "full_name": "Test Owner",
    }
    return _save(db, User(**{**values, **overrides}))


def make_category(db: Session, tenant: Tenant, **overrides: Any) -> Category:
    slug = overrides.pop("slug", f"cat-{short_id()}")
    values: dict[str, Any] = {"tenant_id": tenant.id, "name": slug, "slug": slug}
    return _save(db, Category(**{**values, **overrides}))


def make_product(
    db: Session, tenant: Tenant, category: Category | None = None, **overrides: Any
) -> Product:
    category = category or make_category(db, tenant)
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "sku": f"SKU-{short_id()}",
        "name": "Biscuits 100 g",
        "category_id": category.id,
        "base_unit": "pack",
        "tax_rate_id": tax_rate(db).id,
        "mrp": Decimal("10.00"),
        "selling_price": Decimal("9.50"),
    }
    return _save(db, Product(**{**values, **overrides}))


def make_supplier(db: Session, tenant: Tenant, **overrides: Any) -> Supplier:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "code": f"SUP-{short_id()}",
        "name": "Test Supplier",
    }
    return _save(db, Supplier(**{**values, **overrides}))


def make_terms(
    db: Session, tenant: Tenant, supplier: Supplier, product: Product, **overrides: Any
) -> SupplierProductTerm:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "supplier_id": supplier.id,
        "product_id": product.id,
        "purchase_price": Decimal("8.0000"),
        "effective_from": date(2026, 1, 1),
    }
    return _save(db, SupplierProductTerm(**{**values, **overrides}))


def make_batch(db: Session, tenant: Tenant, product: Product, **overrides: Any) -> ProductBatch:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "product_id": product.id,
        "batch_no": f"B-{short_id()}",
        "expiry_date": date(2027, 6, 30),
        "unit_cost": Decimal("8.0000"),
        "received_on": BUSINESS_DATE,
        "initial_qty": Decimal("100.000"),
    }
    return _save(db, ProductBatch(**{**values, **overrides}))


def make_balance(
    db: Session,
    tenant: Tenant,
    product: Product,
    batch: ProductBatch | None = None,
    **overrides: Any,
) -> StockBalance:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "product_id": product.id,
        "batch_id": batch.id if batch else None,
        "on_hand": Decimal("10.000"),
    }
    return _save(db, StockBalance(**{**values, **overrides}))


def make_movement(
    db: Session, tenant: Tenant, product: Product, **overrides: Any
) -> InventoryMovement:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "product_id": product.id,
        "movement_type": "opening",
        "quantity_delta": Decimal("10.000"),
        "occurred_at": SOME_INSTANT,
        "business_date": BUSINESS_DATE,
        "source_type": "opening",
        "source_id": "opening-1",
    }
    return _save(db, InventoryMovement(**{**values, **overrides}))


def make_sale(db: Session, tenant: Tenant, **overrides: Any) -> Sale:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "bill_no": f"B-{short_id()}",
        "business_date": BUSINESS_DATE,
        "sold_at": SOME_INSTANT,
        "payment_mode": "cash",
        "subtotal": Decimal("19.00"),
        "total": Decimal("19.00"),
    }
    return _save(db, Sale(**{**values, **overrides}))


def make_sale_line(
    db: Session, tenant: Tenant, sale: Sale, product: Product, **overrides: Any
) -> SaleLine:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "sale_id": sale.id,
        "product_id": product.id,
        "quantity": Decimal("2.000"),
        "unit_price": Decimal("9.5000"),
        "tax_rate_pct": Decimal("5.00"),
        "line_total": Decimal("19.00"),
        "business_date": BUSINESS_DATE,
    }
    return _save(db, SaleLine(**{**values, **overrides}))


def make_po(db: Session, tenant: Tenant, supplier: Supplier, **overrides: Any) -> PurchaseOrder:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "supplier_id": supplier.id,
        "po_number": f"PO-{short_id()}",
        "order_date": BUSINESS_DATE,
    }
    return _save(db, PurchaseOrder(**{**values, **overrides}))


def make_po_line(
    db: Session, tenant: Tenant, po: PurchaseOrder, product: Product, **overrides: Any
) -> PurchaseOrderLine:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "po_id": po.id,
        "product_id": product.id,
        "quantity_ordered": Decimal("20.000"),
        "unit_cost": Decimal("8.0000"),
        "pack_size": Decimal("10.000"),
    }
    return _save(db, PurchaseOrderLine(**{**values, **overrides}))


def make_model_version(db: Session, **overrides: Any) -> ModelVersion:
    values: dict[str, Any] = {"name": "forecast-engine", "version": f"test-{short_id()}"}
    return _save(db, ModelVersion(**{**values, **overrides}))


def make_forecast_run(db: Session, tenant: Tenant, **overrides: Any) -> ForecastRun:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "kind": "weekly",
        "profile": "light",
        "data_cutoff": SOME_INSTANT,
        "as_of_date": BUSINESS_DATE,
        "horizon_days": 28,
        "model_version_id": make_model_version(db).id,
        "status": "succeeded",
    }
    return _save(db, ForecastRun(**{**values, **overrides}))


def make_recommendation_run(
    db: Session, tenant: Tenant, forecast_run: ForecastRun | None = None, **overrides: Any
) -> RecommendationRun:
    forecast_run = forecast_run or make_forecast_run(db, tenant)
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "forecast_run_id": forecast_run.id,
        "as_of_date": BUSINESS_DATE,
        "data_cutoff": SOME_INSTANT,
        "status": "succeeded",
        "model_version_id": forecast_run.model_version_id,
    }
    return _save(db, RecommendationRun(**{**values, **overrides}))


def make_recommendation_line(
    db: Session, tenant: Tenant, run: RecommendationRun, product: Product, **overrides: Any
) -> RecommendationLine:
    zero = Decimal("0.000")
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "run_id": run.id,
        "product_id": product.id,
        "sections": ["buy"],
        "protection_days": 10,
        "lead_time_days": 3,
        "lead_time_source": "business_default",
        "avg_daily_forecast": Decimal("3.0000"),
        "demand_7d": Decimal("21.000"),
        "demand_protection": Decimal("30.000"),
        "on_hand_usable": Decimal("12.000"),
        "inventory_position": Decimal("17.000"),
        "safety_stock": Decimal("4.000"),
        "target_level": Decimal("34.000"),
        "raw_qty": Decimal("17.000"),
        "moq_units": zero,
        "pack_size": Decimal("10.000"),
        "suggested_qty": Decimal("20.000"),
        "allocated_qty": Decimal("20.000"),
        "stockout_probability": Decimal("0.300"),
        "risk_level": "high",
        "confidence": "medium",
        "forecast_method": "moving_average",
        "reason_text": "Demand for the next 10 days is about 30 packs.",
    }
    return _save(db, RecommendationLine(**{**values, **overrides}))


def make_decision(
    db: Session, tenant: Tenant, line: RecommendationLine, user: User, **overrides: Any
) -> RecommendationDecision:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "line_id": line.id,
        "decided_by": user.id,
        "decision": "approved",
        "final_qty": line.suggested_qty,
    }
    return _save(db, RecommendationDecision(**{**values, **overrides}))


def make_report(
    db: Session, tenant: Tenant, run: RecommendationRun, **overrides: Any
) -> WeeklyReport:
    values: dict[str, Any] = {
        "tenant_id": tenant.id,
        "week_start": BUSINESS_DATE,
        "recommendation_run_id": run.id,
        "forecast_run_id": run.forecast_run_id,
        "data_cutoff": SOME_INSTANT,
        "status": "ready",
        "payload": {},
        "model_version": "test",
    }
    return _save(db, WeeklyReport(**{**values, **overrides}))
