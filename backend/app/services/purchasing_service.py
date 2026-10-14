"""Purchase orders and goods receipts.

A receipt is one transaction: it creates batches for batch tracked products, writes `receipt`
movements through the ledger (which keeps the weighted average cost), updates the order lines'
received quantities and moves the order to `partially_received` or `received`.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService
from app.core.clock import now_utc, today_ist
from app.core.db import advisory_lock, transaction
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.money import round_money
from app.core.pagination import PageParams, paginate, parse_sort
from app.core.repo import TenantRepo
from app.engine.lead_time import LeadTime, expected_delivery_date, resolve_lead_time
from app.engine.po_rules import (
    OPEN_STATUSES,
    days_late,
    invoice_differs,
    is_overdue,
    next_status,
    open_quantity,
    price_variance,
    status_after_receipt,
)
from app.models.catalogue import Product
from app.models.inventory import ProductBatch
from app.models.purchasing import GoodsReceipt, PurchaseOrder, PurchaseOrderLine, ReceiptLine
from app.models.suppliers import Supplier
from app.schemas.common import ErrorDetail
from app.schemas.purchasing import (
    DirectReceiptCreate,
    POCreate,
    POLineIn,
    POLineOut,
    POListItem,
    POOut,
    POPatch,
    ReceiptCreate,
    ReceiptLineBase,
    ReceiptLineOut,
    ReceiptListItem,
    ReceiptOut,
    ReceiptSummary,
    ReceiptWarning,
    TimelineEvent,
)
from app.services.catalogue_service import ProductRepo, SupplierRepo
from app.services.common import conflict, escape_like, invalid, next_number, not_found
from app.services.ledger import LedgerService, MovementEntry
from app.services.sales_service import fmt_qty
from app.services.supplier_service import business_lead_time, find_term

ZERO = Decimal(0)
INVALID_STATE = "This order cannot be changed in its current state."


class PORepo(TenantRepo[PurchaseOrder]):
    model = PurchaseOrder


class POLineRepo(TenantRepo[PurchaseOrderLine]):
    model = PurchaseOrderLine


class ReceiptRepo(TenantRepo[GoodsReceipt]):
    model = GoodsReceipt


def state_error(message: str = INVALID_STATE) -> AppError:
    return AppError(ErrorCode.PO_STATE_INVALID, message)


class PurchasingService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.orders = PORepo(session, ctx.tenant_id)
        self.order_lines = POLineRepo(session, ctx.tenant_id)
        self.receipts = ReceiptRepo(session, ctx.tenant_id)
        self.suppliers = SupplierRepo(session, ctx.tenant_id)
        self.products = ProductRepo(session, ctx.tenant_id)
        self.ledger = LedgerService(session, ctx.tenant_id, ctx.user_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ reads

    def get(self, po_id: uuid.UUID) -> POOut:
        po = self.orders.get(po_id)
        if po is None:
            raise not_found("order")
        return self._out(po)

    def _out(self, po: PurchaseOrder) -> POOut:
        supplier = self.suppliers.get(po.supplier_id)
        rows = self.session.execute(
            select(PurchaseOrderLine, Product.sku, Product.name)
            .join(
                Product,
                and_(
                    Product.tenant_id == PurchaseOrderLine.tenant_id,
                    Product.id == PurchaseOrderLine.product_id,
                ),
            )
            .where(
                PurchaseOrderLine.tenant_id == self.ctx.tenant_id, PurchaseOrderLine.po_id == po.id
            )
            .order_by(Product.name, PurchaseOrderLine.created_at)
        ).all()
        lines = [
            POLineOut(
                id=line.id,
                product_id=line.product_id,
                product_sku=sku,
                product_name=name,
                quantity_ordered=line.quantity_ordered,
                quantity_received=line.quantity_received,
                quantity_open=open_quantity(line.quantity_ordered, line.quantity_received),
                unit_cost=line.unit_cost,
                pack_size=line.pack_size,
                line_value=round_money(line.quantity_ordered * line.unit_cost),
            )
            for line, sku, name in rows
        ]
        posted = receipt_rows_list(self, po)
        totals = self._receipt_totals([r.id for r in posted])
        receipts = [
            ReceiptSummary(
                id=r.id,
                receipt_no=r.receipt_no,
                received_on=r.received_on,
                created_at=r.created_at,
                invoice_no=r.invoice_no,
                invoice_total=r.invoice_total,
                is_exception=r.is_exception,
                lines_total=totals.get(r.id, ZERO),
            )
            for r in posted
        ]
        today = today_ist()
        return POOut(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            supplier_name=supplier.name if supplier else "",
            status=po.status,  # type: ignore[arg-type]
            order_date=po.order_date,
            expected_date=po.expected_date,
            is_overdue=is_overdue(po.status, po.expected_date, today),
            days_late=days_late(po.status, po.expected_date, today),
            sent_at=po.sent_at,
            cancelled_at=po.cancelled_at,
            cancel_reason=po.cancel_reason,
            subtotal_estimated=po.subtotal_estimated,
            source=po.source,
            notes=po.notes,
            created_at=po.created_at,
            lines=lines,
            receipts=receipts,
            timeline=self._timeline(po, receipts),
        )

    @staticmethod
    def _timeline(po: PurchaseOrder, receipts: list[ReceiptSummary]) -> list[TimelineEvent]:
        events = [TimelineEvent(event="created", at=po.created_at)]
        if po.sent_at:
            events.append(TimelineEvent(event="sent", at=po.sent_at))
        events.extend(
            TimelineEvent(event="received", at=r.created_at, detail=r.receipt_no) for r in receipts
        )
        if po.cancelled_at:
            events.append(
                TimelineEvent(event="cancelled", at=po.cancelled_at, detail=po.cancel_reason)
            )
        if po.status == "closed":
            events.append(TimelineEvent(event="closed", at=po.updated_at))
        return events  # already in the order things can happen: sent, then received, then closed

    def _receipt_totals(self, receipt_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        if not receipt_ids:
            return {}
        rows = self.session.execute(
            select(
                ReceiptLine.receipt_id,
                func.round(func.sum(ReceiptLine.quantity_received * ReceiptLine.unit_cost), 2),
            )
            .where(
                ReceiptLine.tenant_id == self.ctx.tenant_id, ReceiptLine.receipt_id.in_(receipt_ids)
            )
            .group_by(ReceiptLine.receipt_id)
        ).all()
        return {rid: Decimal(total) for rid, total in rows}

    def search(
        self,
        *,
        page: PageParams,
        status: str | None,
        supplier_id: uuid.UUID | None,
        overdue: bool | None,
        q: str | None,
        start: date | None,
        end: date | None,
        sort: str | None,
    ) -> tuple[list[POListItem], int]:
        today = today_ist()
        counts = (
            select(
                PurchaseOrderLine.po_id.label("po_id"),
                func.count().label("n"),
                func.coalesce(
                    func.round(
                        func.sum(PurchaseOrderLine.quantity_received * PurchaseOrderLine.unit_cost),
                        2,
                    ),
                    ZERO,
                ).label("received_value"),
            )
            .where(PurchaseOrderLine.tenant_id == self.ctx.tenant_id)
            .group_by(PurchaseOrderLine.po_id)
            .subquery()
        )
        stmt = (
            self.orders.select_()
            .add_columns(
                Supplier.name,
                func.coalesce(counts.c.n, 0),
                func.coalesce(counts.c.received_value, ZERO),
            )
            .join(
                Supplier,
                and_(
                    Supplier.tenant_id == PurchaseOrder.tenant_id,
                    Supplier.id == PurchaseOrder.supplier_id,
                ),
            )
            .outerjoin(counts, counts.c.po_id == PurchaseOrder.id)
        )
        if status is not None:
            stmt = stmt.where(PurchaseOrder.status == status)
        if supplier_id is not None:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        if overdue is not None:
            late = and_(
                PurchaseOrder.status.in_(OPEN_STATUSES),
                PurchaseOrder.expected_date.is_not(None),
                PurchaseOrder.expected_date < today,
            )
            stmt = stmt.where(late if overdue else ~late)
        if start is not None:
            stmt = stmt.where(PurchaseOrder.order_date >= start)
        if end is not None:
            stmt = stmt.where(PurchaseOrder.order_date <= end)
        term = (q or "").strip()
        if term:
            stmt = stmt.where(PurchaseOrder.po_number.ilike(f"%{escape_like(term)}%", escape="\\"))
        order = parse_sort(
            sort,
            {
                "order_date": PurchaseOrder.order_date,
                "expected_date": PurchaseOrder.expected_date,
                "po_number": PurchaseOrder.po_number,
                "value": PurchaseOrder.subtotal_estimated,
            },
            "order_date:desc",
        )
        rows, total = paginate(self.session, stmt.order_by(*order, PurchaseOrder.id), page)
        items = [
            POListItem(
                id=po.id,
                po_number=po.po_number,
                supplier_id=po.supplier_id,
                supplier_name=supplier_name,
                status=po.status,  # type: ignore[arg-type]
                order_date=po.order_date,
                expected_date=po.expected_date,
                is_overdue=is_overdue(po.status, po.expected_date, today),
                days_late=days_late(po.status, po.expected_date, today),
                lines=int(n),
                value=po.subtotal_estimated,
                received_value=received_value,
            )
            for po, supplier_name, n, received_value in rows
        ]
        return items, total

    # ------------------------------------------------------------------ create and edit

    def create(self, body: POCreate) -> POOut:
        with transaction(self.session):
            supplier = self._require_supplier(body.supplier_id)
            today = today_ist()
            if body.expected_date is not None and body.expected_date < today:
                raise invalid("expected_date", "cannot be before today")
            advisory_lock(self.session, self.ctx.tenant_id, "po-number")
            resolved = self._resolve_lines(supplier, body.lines, today)
            expected = body.expected_date or self._default_expected(supplier, resolved, today)
            po = self.orders.add(
                PurchaseOrder(
                    supplier_id=supplier.id,
                    po_number=next_number(
                        self.session,
                        self.ctx.tenant_id,
                        PurchaseOrder.po_number,
                        PurchaseOrder.tenant_id,
                        prefix="PO",
                        on=today,
                        width=4,
                    ),
                    status="draft",
                    order_date=today,
                    expected_date=expected,
                    subtotal_estimated=sum((r.value for r in resolved), ZERO),
                    source="manual",
                    notes=body.notes,
                    created_by=self.ctx.user_id,
                )
            )
            self.session.flush()
            self._add_lines(po, resolved)
            self.audit.record(
                AuditAction.PO_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="purchase_order",
                entity_id=po.id,
                after={
                    "po_number": po.po_number,
                    "supplier_id": supplier.id,
                    "lines": len(resolved),
                    "value": po.subtotal_estimated,
                },
            )
            return self._out(po)

    def update(self, po_id: uuid.UUID, body: POPatch) -> POOut:
        with transaction(self.session):
            po = self._locked(po_id)
            if po.status != "draft":
                raise state_error("Only a draft order can be edited.")
            today = today_ist()
            changed: dict[str, Any] = {}
            if "expected_date" in body.model_fields_set:
                if body.expected_date is not None and body.expected_date < today:
                    raise invalid("expected_date", "cannot be before today")
                po.expected_date = body.expected_date
                changed["expected_date"] = body.expected_date
            if "notes" in body.model_fields_set:
                po.notes = body.notes
                changed["notes"] = body.notes
            if body.lines is not None:
                supplier = self._require_supplier(po.supplier_id)
                resolved = self._resolve_lines(supplier, body.lines, today)
                for old in self.session.execute(
                    self.order_lines.select_().where(PurchaseOrderLine.po_id == po.id)
                ).scalars():
                    self.session.delete(old)
                self.session.flush()
                self._add_lines(po, resolved)
                po.subtotal_estimated = sum((r.value for r in resolved), ZERO)
                changed["lines"] = len(resolved)
                changed["value"] = po.subtotal_estimated
            self.session.flush()
            if changed:
                self.audit.record(
                    AuditAction.PO_UPDATE,
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    meta=self.ctx.meta,
                    entity_type="purchase_order",
                    entity_id=po.id,
                    after=changed,
                )
            return self._out(po)

    def _require_supplier(self, supplier_id: uuid.UUID) -> Supplier:
        supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise not_found("supplier", field="supplier_id")
        if not supplier.is_active:
            raise invalid("supplier_id", "is switched off")
        return supplier

    def _resolve_lines(
        self, supplier: Supplier, lines: list[POLineIn], today: date
    ) -> list["_ResolvedLine"]:
        """Products, cost, pack size and lead time for each requested line."""
        ids = [line.product_id for line in lines]
        found = {
            p.id: p
            for p in self.session.execute(
                self.products.select_().where(Product.id.in_(ids))
            ).scalars()
        }
        business_days = business_lead_time(self.session, self.ctx.tenant_id)
        seen: set[uuid.UUID] = set()
        resolved: list[_ResolvedLine] = []
        missing: list[ErrorDetail] = []
        for index, line in enumerate(lines):
            product = found.get(line.product_id)
            field = f"lines[{index}].product_id"
            if product is None:
                raise not_found("product", field=field)
            if not product.is_active:
                raise invalid(field, "is switched off")
            if product.id in seen:
                raise invalid(field, "is listed twice")
            seen.add(product.id)
            term = find_term(
                self.session, self.ctx.tenant_id, product.id, today, supplier_id=supplier.id
            )
            cost = (
                line.unit_cost
                if line.unit_cost is not None
                else (term.purchase_price if term else None)
            )
            if cost is None:
                missing.append(
                    ErrorDetail(
                        field=f"lines[{index}].unit_cost", issue=f"no price for {product.name}"
                    )
                )
                continue
            lead = resolve_lead_time(
                term.lead_time_days if term else None,
                supplier.default_lead_time_days,
                business_days,
            )
            resolved.append(
                _ResolvedLine(
                    product=product,
                    quantity=line.quantity_ordered,
                    cost=cost,
                    pack_size=term.pack_size if term else Decimal(1),
                    lead=lead,
                    value=round_money(line.quantity_ordered * cost),
                )
            )
        if missing:
            raise AppError(
                ErrorCode.MISSING_SUPPLIER_OR_COST,
                "Add a price for these products first, from this supplier or on the line.",
                details=missing,
            )
        return resolved

    @staticmethod
    def _default_expected(supplier: Supplier, resolved: list["_ResolvedLine"], today: date) -> date:
        slowest = max(resolved, key=lambda r: r.lead.days).lead
        return expected_delivery_date(today, slowest, supplier.delivery_weekdays)

    def _add_lines(self, po: PurchaseOrder, resolved: list["_ResolvedLine"]) -> None:
        self.session.add_all(
            PurchaseOrderLine(
                tenant_id=self.ctx.tenant_id,
                po_id=po.id,
                product_id=r.product.id,
                quantity_ordered=r.quantity,
                unit_cost=r.cost,
                pack_size=r.pack_size,
            )
            for r in resolved
        )
        self.session.flush()

    def _locked(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = self.session.execute(
            self.orders.select_().where(PurchaseOrder.id == po_id).with_for_update()
        ).scalar_one_or_none()
        if po is None:
            raise not_found("order")
        return po

    # ------------------------------------------------------------------ state changes

    def send(self, po_id: uuid.UUID) -> POOut:
        with transaction(self.session):
            po = self._locked(po_id)
            self._move(po, "send", "Only a draft order can be sent.")
            po.sent_at = now_utc()
            self._finish(po, AuditAction.PO_SEND, before="draft")
            return self._out(po)

    def cancel(self, po_id: uuid.UUID, reason: str | None) -> POOut:
        with transaction(self.session):
            po = self._locked(po_id)
            before = po.status
            self._move(po, "cancel", "Only an order that has not arrived can be cancelled.")
            po.cancelled_at = now_utc()
            po.cancel_reason = reason
            self._finish(po, AuditAction.PO_CANCEL, before=before, extra={"reason": reason})
            return self._out(po)

    def close(self, po_id: uuid.UUID) -> POOut:
        with transaction(self.session):
            po = self._locked(po_id)
            before = po.status
            self._move(po, "close", "A draft or cancelled order cannot be closed.")
            self._finish(po, AuditAction.PO_CLOSE, before=before)
            return self._out(po)

    def _move(self, po: PurchaseOrder, action: Any, message: str) -> None:
        target = next_status(po.status, action)
        if target is None:
            raise state_error(message)
        if action == "send" and not self._has_lines(po):
            raise state_error("Add at least one product before sending.")
        po.status = "closed" if action == "close" else target

    def _has_lines(self, po: PurchaseOrder) -> bool:
        return (
            self.session.execute(
                self.order_lines.select_().where(PurchaseOrderLine.po_id == po.id).limit(1)
            ).first()
            is not None
        )

    def _finish(
        self,
        po: PurchaseOrder,
        action: AuditAction,
        *,
        before: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.session.flush()
        self.audit.record(
            action,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="purchase_order",
            entity_id=po.id,
            before={"status": before},
            after={"status": po.status, "po_number": po.po_number, **(extra or {})},
        )

    # ------------------------------------------------------------------ receipts

    def receive(
        self, po_id: uuid.UUID, body: ReceiptCreate, *, idempotency_key: str | None = None
    ) -> ReceiptOut:
        with transaction(self.session):
            po = self._locked(po_id)
            if po.status not in OPEN_STATUSES:
                raise state_error(
                    "Goods can only be received against an order that was sent and is not closed."
                )
            order_lines = {
                line.id: line
                for line in self.session.execute(
                    self.order_lines.select_()
                    .where(PurchaseOrderLine.po_id == po.id)
                    .with_for_update()
                ).scalars()
            }
            products = self._products_for(
                [
                    (i, order_lines[line.po_line_id].product_id)
                    for i, line in enumerate(body.lines)
                    if line.po_line_id in order_lines
                ]
            )
            for index, line in enumerate(body.lines):
                if line.po_line_id not in order_lines:
                    raise not_found("order line", field=f"lines[{index}].po_line_id")

            arriving: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
            for line in body.lines:
                arriving[line.po_line_id] += line.quantity_received
            over = [
                ErrorDetail(
                    field="lines",
                    issue=(
                        f"{products_name(products, order_lines[lid].product_id)}: "
                        f"{fmt_qty(qty)} arrived, {fmt_qty(_open(order_lines[lid]))} still open"
                    ),
                )
                for lid, qty in arriving.items()
                if qty
                > open_quantity(
                    order_lines[lid].quantity_ordered, order_lines[lid].quantity_received
                )
            ]
            if over and not body.is_exception:
                raise AppError(ErrorCode.RECEIPT_EXCEEDS_ORDER, details=over)

            receipt = self._post_receipt(
                supplier_id=po.supplier_id,
                po=po,
                header=body,
                lines=[
                    (line, order_lines[line.po_line_id].product_id, line.po_line_id)
                    for line in body.lines
                ],
                idempotency_key=idempotency_key,
            )
            warnings: list[ReceiptWarning] = []
            for index, line in enumerate(body.lines):
                po_line = order_lines[line.po_line_id]
                name = products_name(products, po_line.product_id)
                change = price_variance(po_line.unit_cost, line.unit_cost)
                if change is not None:
                    direction = "more" if change > 0 else "less"
                    warnings.append(
                        ReceiptWarning(
                            code="PRICE_VARIANCE",
                            line_index=index,
                            message=(
                                f"{name} cost {abs(round(change * 100))} percent "
                                f"{direction} than on the order."
                            ),
                        )
                    )
            for lid, qty in arriving.items():
                po_line = order_lines[lid]
                available = open_quantity(po_line.quantity_ordered, po_line.quantity_received)
                if qty > available:
                    warnings.append(
                        ReceiptWarning(
                            code="OVER_RECEIPT",
                            message=(
                                f"{products_name(products, po_line.product_id)}: "
                                f"{fmt_qty(qty - available)} more than ordered."
                            ),
                        )
                    )
                po_line.quantity_received = po_line.quantity_received + qty
            po.status = status_after_receipt(
                [(item.quantity_ordered, item.quantity_received) for item in order_lines.values()]
            )
            self.session.flush()
            for lid in arriving:
                po_line = order_lines[lid]
                left = open_quantity(po_line.quantity_ordered, po_line.quantity_received)
                if left > 0:
                    warnings.append(
                        ReceiptWarning(
                            code="SHORT_RECEIPT",
                            message=(
                                f"{products_name(products, po_line.product_id)}: "
                                f"{fmt_qty(left)} still to come."
                            ),
                        )
                    )
            warnings.extend(self._invoice_warning(body, list(body.lines)))
            result = self._receipt_out(receipt)
            result.warnings = warnings
            return result

    def receive_direct(
        self, body: DirectReceiptCreate, *, idempotency_key: str | None = None
    ) -> ReceiptOut:
        with transaction(self.session):
            supplier = self._require_supplier(body.supplier_id)
            products = self._products_for(
                [(i, line.product_id) for i, line in enumerate(body.lines)]
            )
            for index, line in enumerate(body.lines):
                if line.product_id not in products:
                    raise not_found("product", field=f"lines[{index}].product_id")
            receipt = self._post_receipt(
                supplier_id=supplier.id,
                po=None,
                header=body,
                lines=[(line, line.product_id, None) for line in body.lines],
                idempotency_key=idempotency_key,
            )
            result = self._receipt_out(receipt)
            result.warnings = self._invoice_warning(body, list(body.lines))
            return result

    def _products_for(self, pairs: list[tuple[int, uuid.UUID]]) -> dict[uuid.UUID, Product]:
        ids = {pid for _, pid in pairs}
        return {
            p.id: p
            for p in self.session.execute(
                self.products.select_().where(Product.id.in_(ids))
            ).scalars()
        }

    def _post_receipt(
        self,
        *,
        supplier_id: uuid.UUID,
        po: PurchaseOrder | None,
        header: Any,
        lines: list[tuple[ReceiptLineBase, uuid.UUID, uuid.UUID | None]],
        idempotency_key: str | None,
    ) -> GoodsReceipt:
        today = today_ist()
        received_on: date = header.received_on or today
        if received_on > today:
            raise invalid("received_on", "cannot be in the future")
        if received_on < today - timedelta(days=400):
            raise invalid("received_on", "is too far in the past")

        products = self._products_for([(i, pid) for i, (_, pid, _) in enumerate(lines)])
        for index, (_, pid, _) in enumerate(lines):
            product = products.get(pid)
            if product is None:
                raise not_found("product", field=f"lines[{index}].product_id")
            if po is None and not product.is_active:
                raise invalid(f"lines[{index}].product_id", "is switched off")
        self.ledger.lock_products(products)

        advisory_lock(self.session, self.ctx.tenant_id, "receipt-number")
        receipt = self.receipts.add(
            GoodsReceipt(
                supplier_id=supplier_id,
                purchase_order_id=po.id if po else None,
                receipt_no=next_number(
                    self.session,
                    self.ctx.tenant_id,
                    GoodsReceipt.receipt_no,
                    GoodsReceipt.tenant_id,
                    prefix="GR",
                    on=today,
                    width=4,
                ),
                received_on=received_on,
                invoice_no=header.invoice_no,
                invoice_total=header.invoice_total,
                is_exception=header.is_exception,
                exception_note=header.exception_note,
                idempotency_key=idempotency_key,
                created_by=self.ctx.user_id,
            )
        )
        self.session.flush()

        now = now_utc()
        entries: list[MovementEntry] = []
        rows: list[ReceiptLine] = []
        for index, (line, pid, po_line_id) in enumerate(lines):
            product = products[pid]
            batch = self._batch_for(product, line, received_on, index)
            rows.append(
                ReceiptLine(
                    tenant_id=self.ctx.tenant_id,
                    receipt_id=receipt.id,
                    po_line_id=po_line_id,
                    product_id=pid,
                    batch_id=batch.id if batch else None,
                    quantity_received=line.quantity_received,
                    unit_cost=line.unit_cost,
                    mrp=line.mrp,
                )
            )
            entries.append(
                MovementEntry(
                    product_id=pid,
                    batch_id=batch.id if batch else None,
                    movement_type="receipt",
                    quantity_delta=line.quantity_received,
                    source_type="receipt",
                    source_id=str(receipt.id),
                    unit_cost=line.unit_cost,
                    occurred_at=now,
                )
            )
        self.session.add_all(rows)
        self.session.flush()
        self.ledger.post(entries)
        self.audit.record(
            AuditAction.RECEIPT_POST,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="goods_receipt",
            entity_id=receipt.id,
            after={
                "receipt_no": receipt.receipt_no,
                "po_number": po.po_number if po else None,
                "supplier_id": supplier_id,
                "lines": len(rows),
                "is_exception": receipt.is_exception,
                "invoice_total": receipt.invoice_total,
            },
        )
        return receipt

    def _batch_for(
        self, product: Product, line: ReceiptLineBase, received_on: date, index: int
    ) -> ProductBatch | None:
        prefix = f"lines[{index}]"
        if not product.is_batch_tracked:
            for name in ("batch_no", "expiry_date", "manufactured_on"):
                if getattr(line, name) is not None:
                    raise invalid(f"{prefix}.{name}", "this product is not tracked by batch")
            return None
        for name, label in (
            ("batch_no", "batch number"),
            ("expiry_date", "expiry date"),
            ("mrp", "MRP"),
        ):
            if getattr(line, name) is None:
                raise invalid(
                    f"{prefix}.{name}",
                    "is required",
                    f"Add the {label} for {product.name}.",
                )
        if line.batch_no is None or line.expiry_date is None:  # checked above, for the type checker
            raise invalid(prefix, "needs a batch number and an expiry date")
        if line.expiry_date <= received_on:
            raise invalid(
                f"{prefix}.expiry_date",
                "must be after the day it arrived",
                f"{product.name} has already expired.",
            )
        if line.manufactured_on is not None and line.manufactured_on > received_on:
            raise invalid(f"{prefix}.manufactured_on", "cannot be after the day it arrived")
        existing = self.session.execute(
            select(ProductBatch)
            .where(
                ProductBatch.tenant_id == self.ctx.tenant_id,
                ProductBatch.product_id == product.id,
                ProductBatch.batch_no == line.batch_no,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if existing is not None:
            if existing.expiry_date != line.expiry_date:
                raise conflict(
                    f"Batch {line.batch_no} of {product.name} is already recorded "
                    "with another expiry date.",
                    field=f"{prefix}.expiry_date",
                )
            if existing.status != "active":
                raise conflict(
                    f"Batch {line.batch_no} of {product.name} is on hold.",
                    field=f"{prefix}.batch_no",
                )
            existing.initial_qty = existing.initial_qty + line.quantity_received
            return existing
        batch = ProductBatch(
            tenant_id=self.ctx.tenant_id,
            product_id=product.id,
            batch_no=line.batch_no,
            expiry_date=line.expiry_date,
            manufactured_on=line.manufactured_on,
            mrp=line.mrp,
            unit_cost=line.unit_cost,
            received_on=received_on,
            initial_qty=line.quantity_received,
        )
        self.session.add(batch)
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise conflict("That batch was just recorded. Try again.") from exc
        return batch

    @staticmethod
    def _invoice_warning(header: Any, lines: list[ReceiptLineBase]) -> list[ReceiptWarning]:
        total = sum((round_money(line.quantity_received * line.unit_cost) for line in lines), ZERO)
        if invoice_differs(header.invoice_total, total):
            return [
                ReceiptWarning(
                    code="INVOICE_TOTAL_DIFFERS",
                    message=f"The invoice total differs from the lines, which add up to {total}.",
                )
            ]
        return []

    def _receipt_out(self, receipt: GoodsReceipt) -> ReceiptOut:
        supplier = self.suppliers.get(receipt.supplier_id)
        po = self.orders.get(receipt.purchase_order_id) if receipt.purchase_order_id else None
        rows = self.session.execute(
            select(
                ReceiptLine,
                Product.sku,
                Product.name,
                ProductBatch.batch_no,
                ProductBatch.expiry_date,
            )
            .join(
                Product,
                and_(
                    Product.tenant_id == ReceiptLine.tenant_id, Product.id == ReceiptLine.product_id
                ),
            )
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == ReceiptLine.tenant_id,
                    ProductBatch.id == ReceiptLine.batch_id,
                ),
            )
            .where(
                ReceiptLine.tenant_id == self.ctx.tenant_id, ReceiptLine.receipt_id == receipt.id
            )
            .order_by(Product.name, ReceiptLine.created_at)
        ).all()
        lines = [
            ReceiptLineOut(
                id=line.id,
                po_line_id=line.po_line_id,
                product_id=line.product_id,
                product_sku=sku,
                product_name=name,
                batch_id=line.batch_id,
                batch_no=batch_no,
                expiry_date=expiry,
                quantity_received=line.quantity_received,
                unit_cost=line.unit_cost,
                mrp=line.mrp,
                line_value=round_money(line.quantity_received * line.unit_cost),
            )
            for line, sku, name, batch_no, expiry in rows
        ]
        return ReceiptOut(
            id=receipt.id,
            receipt_no=receipt.receipt_no,
            supplier_id=receipt.supplier_id,
            supplier_name=supplier.name if supplier else "",
            purchase_order_id=receipt.purchase_order_id,
            po_number=po.po_number if po else None,
            po_status=po.status if po else None,  # type: ignore[arg-type]
            received_on=receipt.received_on,
            invoice_no=receipt.invoice_no,
            invoice_total=receipt.invoice_total,
            status=receipt.status,  # type: ignore[arg-type]
            is_exception=receipt.is_exception,
            exception_note=receipt.exception_note,
            created_at=receipt.created_at,
            lines_total=sum((item.line_value for item in lines), ZERO),
            lines=lines,
        )

    def get_receipt(self, receipt_id: uuid.UUID) -> ReceiptOut:
        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise not_found("receipt")
        return self._receipt_out(receipt)

    def search_receipts(
        self,
        *,
        page: PageParams,
        supplier_id: uuid.UUID | None,
        start: date | None,
        end: date | None,
        q: str | None,
    ) -> tuple[list[ReceiptListItem], int]:
        totals = (
            select(
                ReceiptLine.receipt_id.label("receipt_id"),
                func.count().label("n"),
                func.coalesce(
                    func.round(func.sum(ReceiptLine.quantity_received * ReceiptLine.unit_cost), 2),
                    ZERO,
                ).label("total"),
            )
            .where(ReceiptLine.tenant_id == self.ctx.tenant_id)
            .group_by(ReceiptLine.receipt_id)
            .subquery()
        )
        stmt = (
            self.receipts.select_()
            .add_columns(
                Supplier.name,
                PurchaseOrder.po_number,
                func.coalesce(totals.c.n, 0),
                func.coalesce(totals.c.total, ZERO),
            )
            .join(
                Supplier,
                and_(
                    Supplier.tenant_id == GoodsReceipt.tenant_id,
                    Supplier.id == GoodsReceipt.supplier_id,
                ),
            )
            .outerjoin(
                PurchaseOrder,
                and_(
                    PurchaseOrder.tenant_id == GoodsReceipt.tenant_id,
                    PurchaseOrder.id == GoodsReceipt.purchase_order_id,
                ),
            )
            .outerjoin(totals, totals.c.receipt_id == GoodsReceipt.id)
        )
        if supplier_id is not None:
            stmt = stmt.where(GoodsReceipt.supplier_id == supplier_id)
        if start is not None:
            stmt = stmt.where(GoodsReceipt.received_on >= start)
        if end is not None:
            stmt = stmt.where(GoodsReceipt.received_on <= end)
        term = (q or "").strip()
        if term:
            like = f"%{escape_like(term)}%"
            stmt = stmt.where(
                or_(
                    GoodsReceipt.receipt_no.ilike(like, escape="\\"),
                    GoodsReceipt.invoice_no.ilike(like, escape="\\"),
                )
            )
        rows, total = paginate(
            self.session,
            stmt.order_by(GoodsReceipt.received_on.desc(), GoodsReceipt.receipt_no.desc()),
            page,
        )
        return [
            ReceiptListItem(
                id=r.id,
                receipt_no=r.receipt_no,
                supplier_id=r.supplier_id,
                supplier_name=name,
                po_number=po_number,
                received_on=r.received_on,
                invoice_no=r.invoice_no,
                is_exception=r.is_exception,
                lines=int(n),
                lines_total=line_total,
            )
            for r, name, po_number, n, line_total in rows
        ], total


class _ResolvedLine:
    """A purchase order line after cost, pack size and lead time were worked out."""

    def __init__(
        self,
        *,
        product: Product,
        quantity: Decimal,
        cost: Decimal,
        pack_size: Decimal,
        lead: LeadTime,
        value: Decimal,
    ) -> None:
        self.product = product
        self.quantity = quantity
        self.cost = cost
        self.pack_size = pack_size
        self.lead = lead
        self.value = value


def _open(line: PurchaseOrderLine) -> Decimal:
    return open_quantity(line.quantity_ordered, line.quantity_received)


def products_name(products: dict[uuid.UUID, Product], product_id: uuid.UUID) -> str:
    product = products.get(product_id)
    return product.name if product else "A product"


def receipt_rows_list(service: "PurchasingService", po: PurchaseOrder) -> list[GoodsReceipt]:
    return list(
        service.session.execute(
            service.receipts.select_()
            .where(GoodsReceipt.purchase_order_id == po.id, GoodsReceipt.status == "posted")
            .order_by(GoodsReceipt.created_at)
        ).scalars()
    )
