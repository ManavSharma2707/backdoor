"""Stock levels, batches, movements, adjustments, write offs, counts, stockouts, reconciliation.

Every stock change goes through `LedgerService`. This module adds the documents around it:
`stock_adjustments` for adjustments and write offs, `stock_counts` for counts.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService
from app.core.clock import now_utc, today_ist
from app.core.db import transaction
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.money import round_money
from app.core.pagination import PageParams, paginate, parse_sort
from app.core.repo import TenantRepo
from app.engine.po_rules import OPEN_STATUSES
from app.models.catalogue import Category, Product
from app.models.intelligence import RecommendationLine, RecommendationRun
from app.models.inventory import (
    InventoryMovement,
    ProductBatch,
    StockAdjustment,
    StockBalance,
    StockCount,
    StockCountLine,
    StockoutInterval,
)
from app.models.purchasing import PurchaseOrder, PurchaseOrderLine
from app.models.suppliers import Supplier
from app.models.tenancy import User
from app.schemas.common import ErrorDetail
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentOut,
    BatchRow,
    CountCreate,
    CountLineOut,
    CountLinesPatch,
    CountListItem,
    CountOut,
    MismatchOut,
    MovementRow,
    ProductStockOut,
    ReconcileOut,
    StockoutCreate,
    StockoutOut,
    StockoutPatch,
    StockRow,
    SupplierReturnCreate,
    SupplierReturnOut,
    WriteOffRequest,
)
from app.services.catalogue_service import ProductRepo, SupplierRepo
from app.services.common import conflict, escape_like, invalid, not_found
from app.services.ledger import InsufficientStockError, LedgerService, MovementEntry
from app.services.reconciliation import find_mismatches
from app.services.sales_service import fmt_qty

ZERO = Decimal(0)
MOVEMENT_FOR_REASON = {
    "damage": "damage",
    "expiry_writeoff": "expiry_writeoff",
    "supplier_return": "supplier_return",
}
MAX_COUNT_LINES = 2000


class BatchRepo(TenantRepo[ProductBatch]):
    model = ProductBatch


class CountRepo(TenantRepo[StockCount]):
    model = StockCount


class StockoutRepo(TenantRepo[StockoutInterval]):
    model = StockoutInterval


def shortage_error(exc: InsufficientStockError, names: dict[uuid.UUID, str]) -> AppError:
    first = exc.shortfalls[0]
    return AppError(
        ErrorCode.INSUFFICIENT_STOCK,
        f"Not enough stock for {names.get(first.product_id, 'this product')}: "
        f"{fmt_qty(first.available)} on hand, {fmt_qty(first.requested)} needed.",
        details=[
            ErrorDetail(
                field="quantity_delta",
                issue=f"only {fmt_qty(s.available)} available, {fmt_qty(s.requested)} needed",
            )
            for s in exc.shortfalls
        ],
    )


class InventoryService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.products = ProductRepo(session, ctx.tenant_id)
        self.batches = BatchRepo(session, ctx.tenant_id)
        self.counts = CountRepo(session, ctx.tenant_id)
        self.stockouts = StockoutRepo(session, ctx.tenant_id)
        self.suppliers = SupplierRepo(session, ctx.tenant_id)
        self.ledger = LedgerService(session, ctx.tenant_id, ctx.user_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ stock levels

    def stock_levels(
        self,
        *,
        page: PageParams,
        q: str | None,
        category_id: uuid.UUID | None,
        status: str | None,
        risk: str | None,
        include_inactive: bool,
        sort: str | None,
    ) -> tuple[list[StockRow], int]:
        tid = self.ctx.tenant_id
        today = today_ist()
        sellable_expr = case(
            (StockBalance.batch_id.is_(None), StockBalance.on_hand),
            (
                and_(ProductBatch.status == "active", ProductBatch.expiry_date > today),
                StockBalance.on_hand,
            ),
            else_=ZERO,
        )
        expired_expr = case(
            (and_(ProductBatch.expiry_date <= today, StockBalance.on_hand > 0), 1), else_=0
        )
        stock = (
            select(
                StockBalance.product_id.label("product_id"),
                func.sum(StockBalance.on_hand).label("on_hand"),
                func.sum(StockBalance.reserved_qty).label("reserved"),
                func.sum(sellable_expr).label("sellable"),
                func.sum(StockBalance.on_hand * StockBalance.avg_unit_cost).label("value"),
                func.max(expired_expr).label("has_expired"),
            )
            .select_from(StockBalance)
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == StockBalance.tenant_id,
                    ProductBatch.id == StockBalance.batch_id,
                ),
            )
            .where(StockBalance.tenant_id == tid)
            .group_by(StockBalance.product_id)
            .subquery()
        )
        open_qty = func.greatest(
            PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received, 0
        )
        late = and_(PurchaseOrder.expected_date.is_not(None), PurchaseOrder.expected_date < today)
        incoming = (
            select(
                PurchaseOrderLine.product_id.label("product_id"),
                func.sum(case((late, ZERO), else_=open_qty)).label("incoming"),
                func.sum(case((late, open_qty), else_=ZERO)).label("overdue"),
            )
            .join(
                PurchaseOrder,
                and_(
                    PurchaseOrder.tenant_id == PurchaseOrderLine.tenant_id,
                    PurchaseOrder.id == PurchaseOrderLine.po_id,
                ),
            )
            .where(PurchaseOrderLine.tenant_id == tid, PurchaseOrder.status.in_(OPEN_STATUSES))
            .group_by(PurchaseOrderLine.product_id)
            .subquery()
        )
        counted = (
            select(
                StockCountLine.product_id.label("product_id"),
                func.max(StockCount.count_date).label("last_count"),
            )
            .join(
                StockCount,
                and_(
                    StockCount.tenant_id == StockCountLine.tenant_id,
                    StockCount.id == StockCountLine.count_id,
                ),
            )
            .where(
                StockCountLine.tenant_id == tid,
                StockCount.status == "posted",
                StockCountLine.counted_qty.is_not(None),
            )
            .group_by(StockCountLine.product_id)
            .subquery()
        )
        latest_run = (
            select(RecommendationRun.id)
            .where(RecommendationRun.tenant_id == tid, RecommendationRun.status == "succeeded")
            .order_by(RecommendationRun.as_of_date.desc(), RecommendationRun.started_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        risk_sq = (
            select(
                RecommendationLine.product_id.label("product_id"),
                RecommendationLine.risk_level.label("risk_level"),
            )
            .where(RecommendationLine.tenant_id == tid, RecommendationLine.run_id == latest_run)
            .subquery()
        )

        on_hand = func.coalesce(stock.c.on_hand, ZERO)
        stmt = (
            self.products.select_()
            .add_columns(
                Category.name.label("category_name"),
                on_hand.label("on_hand"),
                func.coalesce(stock.c.sellable, ZERO).label("sellable"),
                func.coalesce(stock.c.reserved, ZERO).label("reserved"),
                func.coalesce(stock.c.value, ZERO).label("value"),
                func.coalesce(stock.c.has_expired, 0).label("has_expired"),
                func.coalesce(incoming.c.incoming, ZERO).label("incoming"),
                func.coalesce(incoming.c.overdue, ZERO).label("overdue"),
                counted.c.last_count.label("last_count"),
                risk_sq.c.risk_level.label("risk_level"),
            )
            .join(
                Category,
                and_(Category.tenant_id == Product.tenant_id, Category.id == Product.category_id),
            )
            .outerjoin(stock, stock.c.product_id == Product.id)
            .outerjoin(incoming, incoming.c.product_id == Product.id)
            .outerjoin(counted, counted.c.product_id == Product.id)
            .outerjoin(risk_sq, risk_sq.c.product_id == Product.id)
        )
        if not include_inactive:
            stmt = stmt.where(Product.is_active.is_(True))
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        term = (q or "").strip()
        if term:
            like = f"%{escape_like(term)}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(like, escape="\\"),
                    Product.sku.ilike(like, escape="\\"),
                    Product.brand.ilike(like, escape="\\"),
                    Product.generic_name.ilike(like, escape="\\"),
                    Product.barcode == term,
                )
            )
        if status == "out":
            stmt = stmt.where(on_hand <= 0)
        elif status == "low":
            stmt = stmt.where(on_hand > 0, on_hand <= Product.min_stock_qty)
        elif status == "ok":
            stmt = stmt.where(on_hand > Product.min_stock_qty)
        elif status == "expired":
            stmt = stmt.where(func.coalesce(stock.c.has_expired, 0) > 0)
        if risk is not None:
            stmt = stmt.where(risk_sq.c.risk_level == risk)
        order = parse_sort(
            sort,
            {
                "name": func.lower(Product.name),
                "sku": Product.sku,
                "on_hand": on_hand,
                "value": func.coalesce(stock.c.value, ZERO),
            },
            "name:asc",
        )
        rows, total = paginate(self.session, stmt.order_by(*order, Product.id), page)
        items = [self._stock_row(r) for r in rows]
        return items, total

    @staticmethod
    def _stock_row(row: Any) -> StockRow:
        product: Product = row[0]
        if row.has_expired:
            state = "expired"
        elif row.on_hand <= 0:
            state = "out"
        elif row.on_hand <= product.min_stock_qty:
            state = "low"
        else:
            state = "ok"
        return StockRow(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            category_id=product.category_id,
            category_name=row.category_name,
            base_unit=product.base_unit,
            is_batch_tracked=product.is_batch_tracked,
            is_active=product.is_active,
            on_hand=row.on_hand,
            sellable=max(row.sellable - row.reserved, ZERO),
            reserved=row.reserved,
            incoming=row.incoming,
            incoming_overdue=row.overdue,
            min_stock_qty=product.min_stock_qty,
            value=round_money(row.value),
            status=state,  # type: ignore[arg-type]
            risk_level=row.risk_level,
            last_count_date=row.last_count,
        )

    # ------------------------------------------------------------------ batches

    def batch_rows(
        self,
        *,
        page: PageParams,
        expiring_within_days: int | None,
        expired: bool | None,
        product_id: uuid.UUID | None,
        status: str | None,
        include_empty: bool,
    ) -> tuple[list[BatchRow], int]:
        today = today_ist()
        on_hand = func.coalesce(func.sum(StockBalance.on_hand), ZERO)
        stmt = (
            select(
                ProductBatch,
                Product.sku.label("sku"),
                Product.name.label("name"),
                on_hand.label("on_hand"),
            )
            .join(
                Product,
                and_(
                    Product.tenant_id == ProductBatch.tenant_id,
                    Product.id == ProductBatch.product_id,
                ),
            )
            .outerjoin(
                StockBalance,
                and_(
                    StockBalance.tenant_id == ProductBatch.tenant_id,
                    StockBalance.batch_id == ProductBatch.id,
                ),
            )
            .where(ProductBatch.tenant_id == self.ctx.tenant_id)
            .group_by(ProductBatch.id, Product.sku, Product.name)
        )
        if product_id is not None:
            stmt = stmt.where(ProductBatch.product_id == product_id)
        if status is not None:
            stmt = stmt.where(ProductBatch.status == status)
        if expiring_within_days is not None:
            stmt = stmt.where(
                ProductBatch.expiry_date <= today + timedelta(days=expiring_within_days)
            )
        if expired is True:
            stmt = stmt.where(ProductBatch.expiry_date <= today)
        elif expired is False:
            stmt = stmt.where(ProductBatch.expiry_date > today)
        if not include_empty:
            stmt = stmt.having(on_hand > 0)
        rows, total = paginate(
            self.session,
            stmt.order_by(ProductBatch.expiry_date, Product.name, ProductBatch.batch_no),
            page,
        )
        first = self._first_to_sell({row[0].product_id for row in rows}, today)
        return [self._batch_row(r, today, first) for r in rows], total

    def _first_to_sell(self, product_ids: set[uuid.UUID], today: date) -> set[uuid.UUID]:
        """For each product, the sellable batch that expires first (the one to sell first)."""
        if not product_ids:
            return set()
        rows = self.session.execute(
            select(
                ProductBatch.product_id,
                ProductBatch.id,
                ProductBatch.expiry_date,
                ProductBatch.batch_no,
            )
            .join(
                StockBalance,
                and_(
                    StockBalance.tenant_id == ProductBatch.tenant_id,
                    StockBalance.batch_id == ProductBatch.id,
                ),
            )
            .where(
                ProductBatch.tenant_id == self.ctx.tenant_id,
                ProductBatch.product_id.in_(product_ids),
                ProductBatch.status == "active",
                ProductBatch.expiry_date > today,
                StockBalance.on_hand > 0,
            )
            .order_by(ProductBatch.product_id, ProductBatch.expiry_date, ProductBatch.batch_no)
        ).all()
        best: dict[uuid.UUID, uuid.UUID] = {}
        for product_id, batch_id, _, _ in rows:
            best.setdefault(product_id, batch_id)
        return set(best.values())

    @staticmethod
    def _batch_row(row: Any, today: date, first: set[uuid.UUID]) -> BatchRow:
        batch: ProductBatch = row[0]
        return BatchRow(
            batch_id=batch.id,
            product_id=batch.product_id,
            sku=row.sku,
            name=row.name,
            batch_no=batch.batch_no,
            expiry_date=batch.expiry_date,
            days_to_expiry=(batch.expiry_date - today).days,
            on_hand=row.on_hand,
            unit_cost=batch.unit_cost,
            value=round_money(row.on_hand * batch.unit_cost),
            mrp=batch.mrp,
            status=batch.status,  # type: ignore[arg-type]
            is_expired=batch.expiry_date <= today,
            sell_first=batch.id in first,
        )

    def product_stock(self, product_id: uuid.UUID) -> ProductStockOut:
        product = self.products.get(product_id)
        if product is None:
            raise not_found("product")
        today = today_ist()
        batches, _ = self.batch_rows(
            page=PageParams(page=1, page_size=200),
            expiring_within_days=None,
            expired=None,
            product_id=product_id,
            status=None,
            include_empty=True,
        )
        balances = list(
            self.session.execute(
                select(StockBalance, ProductBatch)
                .outerjoin(
                    ProductBatch,
                    and_(
                        ProductBatch.tenant_id == StockBalance.tenant_id,
                        ProductBatch.id == StockBalance.batch_id,
                    ),
                )
                .where(
                    StockBalance.tenant_id == self.ctx.tenant_id,
                    StockBalance.product_id == product_id,
                )
            ).all()
        )
        total = sum((b.on_hand for b, _ in balances), ZERO)
        sellable = sum(
            (
                b.on_hand
                for b, batch in balances
                if batch is None or (batch.status == "active" and batch.expiry_date > today)
            ),
            ZERO,
        )
        value = sum((b.on_hand * b.avg_unit_cost for b, _ in balances), ZERO)
        return ProductStockOut(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            is_batch_tracked=product.is_batch_tracked,
            on_hand=total,
            sellable=sellable,
            value=round_money(value),
            batches=batches,
        )

    # ------------------------------------------------------------------ movements

    def movement_rows(
        self,
        *,
        page: PageParams,
        product_id: uuid.UUID | None,
        movement_type: str | None,
        start: date | None,
        end: date | None,
    ) -> tuple[list[MovementRow], int]:
        stmt = (
            select(
                InventoryMovement,
                Product.sku.label("sku"),
                Product.name.label("name"),
                ProductBatch.batch_no.label("batch_no"),
                User.full_name.label("by"),
            )
            .join(
                Product,
                and_(
                    Product.tenant_id == InventoryMovement.tenant_id,
                    Product.id == InventoryMovement.product_id,
                ),
            )
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == InventoryMovement.tenant_id,
                    ProductBatch.id == InventoryMovement.batch_id,
                ),
            )
            .outerjoin(User, User.id == InventoryMovement.created_by)
            .where(InventoryMovement.tenant_id == self.ctx.tenant_id)
        )
        if product_id is not None:
            stmt = stmt.where(InventoryMovement.product_id == product_id)
        if movement_type is not None:
            stmt = stmt.where(InventoryMovement.movement_type == movement_type)
        if start is not None:
            stmt = stmt.where(InventoryMovement.business_date >= start)
        if end is not None:
            stmt = stmt.where(InventoryMovement.business_date <= end)
        rows, total = paginate(
            self.session,
            stmt.order_by(InventoryMovement.occurred_at.desc(), InventoryMovement.id.desc()),
            page,
        )
        return [
            MovementRow(
                id=m.id,
                occurred_at=m.occurred_at,
                business_date=m.business_date,
                product_id=m.product_id,
                sku=row.sku,
                name=row.name,
                batch_id=m.batch_id,
                batch_no=row.batch_no,
                movement_type=m.movement_type,  # type: ignore[arg-type]
                quantity_delta=m.quantity_delta,
                unit_cost=m.unit_cost,
                reason_code=m.reason_code,
                note=m.note,
                source_type=m.source_type,
                source_id=m.source_id,
                reverses_movement_id=m.reverses_movement_id,
                created_by_name=row.by,
            )
            for row in rows
            for m in [row[0]]
        ], total

    # ------------------------------------------------------------------ adjustments

    def adjust(
        self, body: AdjustmentCreate, *, idempotency_key: str | None = None
    ) -> AdjustmentOut:
        """Add or remove stock with a reason. Always one ledger movement and one adjustment row."""
        with transaction(self.session):
            adjustment = self._adjust(
                product_id=body.product_id,
                batch_id=body.batch_id,
                delta=body.quantity_delta,
                reason=body.reason_code,
                note=body.note,
                idempotency_key=idempotency_key,
            )
            self.audit.record(
                AuditAction.ADJUSTMENT_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="stock_adjustment",
                entity_id=adjustment.id,
                after={
                    "product_id": adjustment.product_id,
                    "batch_id": adjustment.batch_id,
                    "quantity_delta": adjustment.quantity_delta,
                    "reason_code": adjustment.reason_code,
                },
            )
            return self._adjustment_out(adjustment)

    def _adjust(
        self,
        *,
        product_id: uuid.UUID,
        batch_id: uuid.UUID | None,
        delta: Decimal,
        reason: str,
        note: str | None,
        idempotency_key: str | None = None,
    ) -> StockAdjustment:
        product = self.products.get(product_id)
        if product is None:
            raise not_found("product", field="product_id")
        batch = self._check_batch(product, batch_id)
        if batch is not None and delta > 0 and batch.status in {"closed", "expired"}:
            raise conflict(f"Batch {batch.batch_no} is closed. Receive stock to add to it.")
        now = now_utc()
        adjustment_id = uuid.uuid4()
        try:
            movements = self.ledger.post(
                [
                    MovementEntry(
                        product_id=product.id,
                        batch_id=batch.id if batch else None,
                        movement_type=MOVEMENT_FOR_REASON.get(reason, "adjustment"),
                        quantity_delta=delta,
                        source_type="adjustment",
                        source_id=str(adjustment_id),
                        reason_code=reason,
                        note=note,
                        occurred_at=now,
                    )
                ]
            )
        except InsufficientStockError as exc:
            raise shortage_error(exc, {product.id: product.name}) from exc
        movement = movements[0]
        adjustment = StockAdjustment(
            id=adjustment_id,
            tenant_id=self.ctx.tenant_id,
            product_id=product.id,
            batch_id=batch.id if batch else None,
            quantity_delta=delta,
            reason_code=reason,
            note=note,
            business_date=movement.business_date,
            movement_id=movement.id,
            idempotency_key=idempotency_key,
            created_by=self.ctx.user_id,
        )
        self.session.add(adjustment)
        self.session.flush()
        return adjustment

    def _check_batch(self, product: Product, batch_id: uuid.UUID | None) -> ProductBatch | None:
        if not product.is_batch_tracked:
            if batch_id is not None:
                raise invalid("batch_id", "this product is not tracked by batch")
            return None
        if batch_id is None:
            raise invalid("batch_id", "is required", f"Choose a batch for {product.name}.")
        batch = self.batches.get(batch_id)
        if batch is None or batch.product_id != product.id:
            raise not_found("batch", field="batch_id")
        return batch

    def _adjustment_out(self, adjustment: StockAdjustment) -> AdjustmentOut:
        row = self.session.execute(
            select(Product.sku, Product.name, ProductBatch.batch_no)
            .select_from(Product)
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == Product.tenant_id,
                    ProductBatch.id == adjustment.batch_id,
                ),
            )
            .where(Product.tenant_id == self.ctx.tenant_id, Product.id == adjustment.product_id)
        ).one()
        return AdjustmentOut(
            id=adjustment.id,
            product_id=adjustment.product_id,
            sku=row.sku,
            name=row.name,
            batch_id=adjustment.batch_id,
            batch_no=row.batch_no,
            quantity_delta=adjustment.quantity_delta,
            reason_code=adjustment.reason_code,  # type: ignore[arg-type]
            note=adjustment.note,
            business_date=adjustment.business_date,
            movement_id=adjustment.movement_id,
            on_hand_after=self.ledger.on_hand(adjustment.product_id, adjustment.batch_id),
            created_at=adjustment.created_at,
        )

    def write_off(self, batch_id: uuid.UUID, body: WriteOffRequest) -> AdjustmentOut:
        """Write off whatever is left of a batch because it expired or was damaged."""
        with transaction(self.session):
            batch = self.session.execute(
                self.batches.select_().where(ProductBatch.id == batch_id).with_for_update()
            ).scalar_one_or_none()
            if batch is None:
                raise not_found("batch")
            if body.reason == "expired" and batch.expiry_date > today_ist():
                raise conflict(
                    f"Batch {batch.batch_no} has not expired yet. Choose damaged to write it off."
                )
            remaining = self.ledger.on_hand(batch.product_id, batch.id)
            if remaining <= 0:
                raise conflict(f"Nothing is left in batch {batch.batch_no} to write off.")
            reason = "expiry_writeoff" if body.reason == "expired" else "damage"
            adjustment = self._adjust(
                product_id=batch.product_id,
                batch_id=batch.id,
                delta=-remaining,
                reason=reason,
                note=body.note,
            )
            batch.status = "closed"
            self.session.flush()
            self.audit.record(
                AuditAction.BATCH_WRITE_OFF,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="product_batch",
                entity_id=batch.id,
                after={
                    "batch_no": batch.batch_no,
                    "quantity": remaining,
                    "reason": body.reason,
                    "value": round_money(remaining * batch.unit_cost),
                },
            )
            return self._adjustment_out(adjustment)

    def supplier_return(
        self, supplier_id: uuid.UUID, body: SupplierReturnCreate
    ) -> SupplierReturnOut:
        """Send stock back to a supplier. Expired or expiring batches follow the supplier's
        returns policy."""
        with transaction(self.session):
            supplier = self.suppliers.get(supplier_id)
            if supplier is None:
                raise not_found("supplier")
            today = today_ist()
            self.ledger.lock_products({line.product_id for line in body.lines})
            outs: list[AdjustmentOut] = []
            created: list[StockAdjustment] = []
            for index, line in enumerate(body.lines):
                product = self.products.get(line.product_id)
                if product is None:
                    raise not_found("product", field=f"lines[{index}].product_id")
                batch = self._check_batch(product, line.batch_id)
                if batch is not None:
                    self._check_return_policy(supplier, batch, today, index)
                note = f"Returned to {supplier.name}: {body.note}"
                if body.credit_note_no:
                    note += f" (credit note {body.credit_note_no})"
                created.append(
                    self._adjust(
                        product_id=product.id,
                        batch_id=batch.id if batch else None,
                        delta=-line.quantity,
                        reason="supplier_return",
                        note=note[:500],
                    )
                )
            outs = [self._adjustment_out(a) for a in created]
            self.audit.record(
                AuditAction.SUPPLIER_RETURN,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="supplier",
                entity_id=supplier.id,
                after={"lines": len(created), "credit_note_no": body.credit_note_no},
            )
            return SupplierReturnOut(
                supplier_id=supplier.id, supplier_name=supplier.name, adjustments=outs
            )

    @staticmethod
    def _check_return_policy(
        supplier: Supplier, batch: ProductBatch, today: date, index: int
    ) -> None:
        field = f"lines[{index}].batch_id"
        days_from_expiry = abs((today - batch.expiry_date).days)
        expired = batch.expiry_date <= today
        if expired and not supplier.accepts_expiry_returns:
            raise conflict(f"{supplier.name} does not take back expired stock.", field=field)
        if (
            supplier.accepts_expiry_returns
            and supplier.expiry_return_window_days is not None
            and (
                expired
                or batch.expiry_date - today <= timedelta(days=supplier.expiry_return_window_days)
            )
            and days_from_expiry > supplier.expiry_return_window_days
        ):
            raise conflict(
                f"{supplier.name} only takes expiry returns within "
                f"{supplier.expiry_return_window_days} days of the expiry date.",
                field=field,
            )

    # ------------------------------------------------------------------ counts

    def create_count(self, body: CountCreate) -> CountOut:
        with transaction(self.session):
            count_date = body.count_date or today_ist()
            if count_date > today_ist():
                raise invalid("count_date", "cannot be in the future")
            stmt = self.products.select_().where(Product.is_active.is_(True))
            if body.scope == "category":
                if body.category_id is None or self._category_missing(body.category_id):
                    raise not_found("category", field="category_id")
                stmt = stmt.where(Product.category_id == body.category_id)
            elif body.scope == "products":
                ids = set(body.product_ids or [])
                stmt = stmt.where(Product.id.in_(ids))
            products = list(self.session.execute(stmt.order_by(Product.name)).scalars())
            if body.scope == "products" and len(products) != len(set(body.product_ids or [])):
                raise not_found("product", field="product_ids")

            balances = self.session.execute(
                select(StockBalance)
                .where(
                    StockBalance.tenant_id == self.ctx.tenant_id,
                    StockBalance.product_id.in_([p.id for p in products]),
                )
                .order_by(StockBalance.product_id, StockBalance.batch_id.nulls_first())
            ).scalars()
            by_product: dict[uuid.UUID, list[StockBalance]] = {}
            for balance in balances:
                by_product.setdefault(balance.product_id, []).append(balance)

            count = self.counts.add(
                StockCount(count_date=count_date, note=body.note, created_by=self.ctx.user_id)
            )
            self.session.flush()
            lines: list[StockCountLine] = []
            for product in products:
                rows = by_product.get(product.id, [])
                if product.is_batch_tracked:
                    rows = [r for r in rows if r.on_hand > 0 and r.batch_id is not None]
                    keys = [(r.batch_id, r.on_hand) for r in rows]
                else:
                    keys = [(None, rows[0].on_hand if rows else ZERO)]
                for batch_id, system_qty in keys:
                    lines.append(
                        StockCountLine(
                            tenant_id=self.ctx.tenant_id,
                            count_id=count.id,
                            product_id=product.id,
                            batch_id=batch_id,
                            system_qty=system_qty,
                        )
                    )
            if not lines:
                raise conflict("There is nothing to count for that choice.")
            if len(lines) > MAX_COUNT_LINES:
                raise invalid(
                    "scope", "has too many lines", "Count a category or some products at a time."
                )
            self.session.add_all(lines)
            self.session.flush()
            return self._count_out(count)

    def _category_missing(self, category_id: uuid.UUID) -> bool:
        return (
            self.session.execute(
                select(Category.id).where(
                    Category.tenant_id == self.ctx.tenant_id, Category.id == category_id
                )
            ).first()
            is None
        )

    def list_counts(
        self, *, page: PageParams, status: str | None
    ) -> tuple[list[CountListItem], int]:
        totals = (
            select(
                StockCountLine.count_id.label("count_id"),
                func.count().label("n"),
                func.count(StockCountLine.counted_qty).label("counted"),
            )
            .where(StockCountLine.tenant_id == self.ctx.tenant_id)
            .group_by(StockCountLine.count_id)
            .subquery()
        )
        stmt = (
            self.counts.select_()
            .add_columns(func.coalesce(totals.c.n, 0), func.coalesce(totals.c.counted, 0))
            .outerjoin(totals, totals.c.count_id == StockCount.id)
        )
        if status is not None:
            stmt = stmt.where(StockCount.status == status)
        rows, total = paginate(
            self.session,
            stmt.order_by(StockCount.count_date.desc(), StockCount.created_at.desc()),
            page,
        )
        return [
            CountListItem(
                id=c.id,
                count_date=c.count_date,
                status=c.status,  # type: ignore[arg-type]
                note=c.note,
                posted_at=c.posted_at,
                created_at=c.created_at,
                lines=int(n),
                counted_lines=int(counted),
            )
            for c, n, counted in rows
        ], total

    def get_count(self, count_id: uuid.UUID) -> CountOut:
        count = self.counts.get(count_id)
        if count is None:
            raise not_found("count")
        return self._count_out(count)

    def _count_out(self, count: StockCount) -> CountOut:
        rows = self.session.execute(
            select(
                StockCountLine,
                Product.sku.label("sku"),
                Product.name.label("name"),
                ProductBatch.batch_no.label("batch_no"),
                ProductBatch.expiry_date.label("expiry"),
                func.coalesce(StockBalance.avg_unit_cost, ZERO).label("cost"),
            )
            .join(
                Product,
                and_(
                    Product.tenant_id == StockCountLine.tenant_id,
                    Product.id == StockCountLine.product_id,
                ),
            )
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == StockCountLine.tenant_id,
                    ProductBatch.id == StockCountLine.batch_id,
                ),
            )
            .outerjoin(
                StockBalance,
                and_(
                    StockBalance.tenant_id == StockCountLine.tenant_id,
                    StockBalance.product_id == StockCountLine.product_id,
                    StockBalance.batch_id.is_not_distinct_from(StockCountLine.batch_id),
                ),
            )
            .where(
                StockCountLine.tenant_id == self.ctx.tenant_id, StockCountLine.count_id == count.id
            )
            .order_by(Product.name, ProductBatch.expiry_date.nulls_first(), ProductBatch.batch_no)
            .execution_options(populate_existing=True)
        ).all()
        lines = [
            CountLineOut(
                id=line.id,
                product_id=line.product_id,
                sku=row.sku,
                name=row.name,
                batch_id=line.batch_id,
                batch_no=row.batch_no,
                expiry_date=row.expiry,
                system_qty=line.system_qty,
                counted_qty=line.counted_qty,
                variance=line.variance,
            )
            for row in rows
            for line in [row[0]]
        ]
        variance_value = sum((row[0].variance * row.cost for row in rows if row[0].variance), ZERO)
        return CountOut(
            id=count.id,
            count_date=count.count_date,
            status=count.status,  # type: ignore[arg-type]
            note=count.note,
            posted_at=count.posted_at,
            created_at=count.created_at,
            lines=lines,
            counted_lines=sum(1 for item in lines if item.counted_qty is not None),
            variance_lines=sum(1 for item in lines if item.variance),
            variance_value=round_money(variance_value),
        )

    def enter_counts(self, count_id: uuid.UUID, body: CountLinesPatch) -> CountOut:
        with transaction(self.session):
            count = self.session.execute(
                self.counts.select_().where(StockCount.id == count_id).with_for_update()
            ).scalar_one_or_none()
            if count is None:
                raise not_found("count")
            if count.status != "draft":
                raise conflict("This count has already been posted.")
            lines = {
                line.id: line
                for line in self.session.execute(
                    select(StockCountLine).where(
                        StockCountLine.tenant_id == self.ctx.tenant_id,
                        StockCountLine.count_id == count.id,
                    )
                ).scalars()
            }
            for index, entry in enumerate(body.lines):
                line = lines.get(entry.line_id)
                if line is None:
                    raise not_found("count line", field=f"lines[{index}].line_id")
                line.counted_qty = entry.counted_qty
            self.session.flush()
            for line in lines.values():
                self.session.refresh(line)
            return self._count_out(count)

    def post_count(self, count_id: uuid.UUID) -> CountOut:
        """Post the differences as `count_correction` movements. Only counted lines count."""
        with transaction(self.session):
            count = self.session.execute(
                self.counts.select_().where(StockCount.id == count_id).with_for_update()
            ).scalar_one_or_none()
            if count is None:
                raise not_found("count")
            if count.status != "draft":
                raise conflict("This count has already been posted.")
            lines = list(
                self.session.execute(
                    select(StockCountLine).where(
                        StockCountLine.tenant_id == self.ctx.tenant_id,
                        StockCountLine.count_id == count.id,
                        StockCountLine.counted_qty.is_not(None),
                    )
                ).scalars()
            )
            if not lines:
                raise conflict("Enter at least one counted quantity before posting.")
            for line in lines:
                self.session.refresh(line)
            now = now_utc()
            names = {
                p.id: p.name
                for p in self.session.execute(
                    self.products.select_().where(Product.id.in_({ln.product_id for ln in lines}))
                ).scalars()
            }
            entries = [
                MovementEntry(
                    product_id=line.product_id,
                    batch_id=line.batch_id,
                    movement_type="count_correction",
                    quantity_delta=line.variance,
                    source_type="stock_count",
                    source_id=str(count.id),
                    reason_code="count",
                    occurred_at=now,
                )
                for line in lines
                if line.variance
            ]
            try:
                self.ledger.post(entries)
            except InsufficientStockError as exc:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "Stock changed since this count started, so a difference would take a "
                    "balance below zero. Start a new count.",
                    details=[
                        ErrorDetail(
                            field="lines",
                            issue=f"{names.get(s.product_id, 'A product')}: "
                            f"{fmt_qty(s.available)} on hand now",
                        )
                        for s in exc.shortfalls
                    ],
                ) from exc
            count.status = "posted"
            count.posted_at = now
            self.session.flush()
            result = self._count_out(count)
            self.audit.record(
                AuditAction.COUNT_POST,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="stock_count",
                entity_id=count.id,
                after={
                    "lines_counted": len(lines),
                    "lines_with_difference": len(entries),
                    "variance_value": result.variance_value,
                },
            )
            return result

    # ------------------------------------------------------------------ stockout intervals

    def list_stockouts(
        self,
        *,
        page: PageParams,
        product_id: uuid.UUID | None,
        source: str | None,
        open_only: bool,
    ) -> tuple[list[StockoutOut], int]:
        stmt = (
            self.stockouts.select_()
            .add_columns(Product.sku, Product.name)
            .join(
                Product,
                and_(
                    Product.tenant_id == StockoutInterval.tenant_id,
                    Product.id == StockoutInterval.product_id,
                ),
            )
        )
        if product_id is not None:
            stmt = stmt.where(StockoutInterval.product_id == product_id)
        if source is not None:
            stmt = stmt.where(StockoutInterval.source == source)
        if open_only:
            stmt = stmt.where(StockoutInterval.end_date.is_(None))
        rows, total = paginate(
            self.session, stmt.order_by(StockoutInterval.start_date.desc(), Product.name), page
        )
        return [self._stockout_out(interval, sku, name) for interval, sku, name in rows], total

    @staticmethod
    def _stockout_out(interval: StockoutInterval, sku: str, name: str) -> StockoutOut:
        return StockoutOut(
            id=interval.id,
            product_id=interval.product_id,
            sku=sku,
            name=name,
            start_date=interval.start_date,
            end_date=interval.end_date,
            source=interval.source,  # type: ignore[arg-type]
            note=interval.note,
            days=(interval.end_date - interval.start_date).days + 1 if interval.end_date else None,
            created_at=interval.created_at,
        )

    def record_stockout(self, body: StockoutCreate) -> StockoutOut:
        with transaction(self.session):
            product = self.products.get(body.product_id)
            if product is None:
                raise not_found("product", field="product_id")
            today = today_ist()
            if body.start_date > today:
                raise invalid("start_date", "cannot be in the future")
            if body.end_date is not None and body.end_date > today:
                raise invalid("end_date", "cannot be in the future")
            self._reject_overlap(product.id, body.start_date, body.end_date, exclude=None)
            interval = self.stockouts.add(
                StockoutInterval(
                    product_id=product.id,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    source="recorded",
                    note=body.note,
                    created_by=self.ctx.user_id,
                )
            )
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That out of stock period is already recorded.") from exc
            self._audit_stockout(interval)
            return self._stockout_out(interval, product.sku, product.name)

    def update_stockout(self, interval_id: uuid.UUID, body: StockoutPatch) -> StockoutOut:
        with transaction(self.session):
            interval = self.session.execute(
                self.stockouts.select_().where(StockoutInterval.id == interval_id).with_for_update()
            ).scalar_one_or_none()
            if interval is None:
                raise not_found("out of stock period")
            if interval.source != "recorded":
                raise conflict("Only periods you recorded yourself can be changed.")
            if "end_date" in body.model_fields_set:
                if body.end_date is not None:
                    if body.end_date < interval.start_date:
                        raise invalid("end_date", "cannot be before the start")
                    if body.end_date > today_ist():
                        raise invalid("end_date", "cannot be in the future")
                self._reject_overlap(
                    interval.product_id, interval.start_date, body.end_date, exclude=interval.id
                )
                interval.end_date = body.end_date
            if "note" in body.model_fields_set:
                interval.note = body.note
            self.session.flush()
            self._audit_stockout(interval)
            product = self.products.get(interval.product_id)
            return self._stockout_out(
                interval, product.sku if product else "", product.name if product else ""
            )

    def _reject_overlap(
        self, product_id: uuid.UUID, start: date, end: date | None, *, exclude: uuid.UUID | None
    ) -> None:
        stmt = self.stockouts.select_().where(
            StockoutInterval.product_id == product_id,
            StockoutInterval.source == "recorded",
            or_(StockoutInterval.end_date.is_(None), StockoutInterval.end_date >= start),
        )
        if end is not None:
            stmt = stmt.where(StockoutInterval.start_date <= end)
        if exclude is not None:
            stmt = stmt.where(StockoutInterval.id != exclude)
        if self.session.execute(stmt.limit(1)).first() is not None:
            raise conflict("That overlaps another out of stock period for this product.")

    def _audit_stockout(self, interval: StockoutInterval) -> None:
        self.audit.record(
            AuditAction.STOCKOUT_RECORD,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="stockout_interval",
            entity_id=interval.id,
            after={
                "product_id": interval.product_id,
                "start_date": interval.start_date,
                "end_date": interval.end_date,
            },
        )

    # ------------------------------------------------------------------ reconciliation

    def reconcile(self) -> ReconcileOut:
        found = find_mismatches(self.session, self.ctx.tenant_id)
        with transaction(self.session):
            self.audit.record(
                AuditAction.RECONCILE_RUN,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                after={"mismatches": len(found)},
            )
        return ReconcileOut(
            ok=not found,
            checked_at=now_utc(),
            mismatches=[
                MismatchOut(
                    code=m.code, entity_type=m.entity_type, entity_id=m.entity_id, detail=m.detail
                )
                for m in found
            ],
        )
