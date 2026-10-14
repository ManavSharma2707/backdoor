"""Bills, returns and voids.

Creating a bill is one transaction: validate, lock the stock rows of every product on the bill,
choose batches first-expired-first-out, price the lines, write the bill, the lines and the
`sale` movements, then audit. A refusal at any step rolls all of it back.

Prices include GST (as MRPs do in India), so the tax on a line is the part of its total that is
tax, never an addition to it.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService
from app.core.clock import now_utc, today_ist
from app.core.db import advisory_lock, transaction
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.pagination import PageParams, paginate, parse_sort
from app.core.repo import TenantRepo
from app.core.timeutil import ist_date
from app.engine.ledger_rules import (
    BatchStock,
    allocate_fefo,
    batch_problem,
)
from app.engine.sales_math import gross_amount, refund_for, split_discount, tax_contained
from app.models.catalogue import Product
from app.models.inventory import ProductBatch
from app.models.reference import TaxRate
from app.models.sales import Sale, SaleLine, SaleReturn, SaleReturnLine
from app.schemas.common import ErrorDetail
from app.schemas.sales import (
    ReturnCreate,
    ReturnLineOut,
    ReturnOut,
    SaleCreate,
    SaleLineIn,
    SaleLineOut,
    SaleListItem,
    SaleOut,
    SalesPoint,
    SalesSummary,
    SaleWarning,
)
from app.services.common import conflict, escape_like, invalid, next_number, not_found
from app.services.ledger import BalanceKey, InsufficientStockError, LedgerService, MovementEntry

ZERO = Decimal(0)
DUPLICATE_WINDOW = timedelta(minutes=2)
MAX_FUTURE = timedelta(minutes=5)
MAX_BACKDATE = timedelta(days=400)
MAX_SHORT_NAMES = 4


class SaleRepo(TenantRepo[Sale]):
    model = Sale


class SaleLineRepo(TenantRepo[SaleLine]):
    model = SaleLine


class ReturnRepo(TenantRepo[SaleReturn]):
    model = SaleReturn


def fmt_qty(value: Decimal) -> str:
    """12.000 as `12`, 2.500 as `2.5`."""
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".")


@dataclass
class LinePlan:
    """One requested bill line after validation: what to sell and from which batches."""

    index: int
    request: SaleLineIn
    product: Product
    tax_pct: Decimal
    unit_price: Decimal
    parts: list[tuple[uuid.UUID | None, Decimal]] = field(default_factory=list)


@dataclass(frozen=True)
class Shortage:
    index: int
    product: Product
    needed: Decimal
    have: Decimal


@dataclass(frozen=True)
class PricedItem:
    """One stored bill line: a requested line split by batch, with its money worked out."""

    product_id: uuid.UUID
    batch_id: uuid.UUID | None
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    tax_pct: Decimal
    gross: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class PricedBill:
    items: list[PricedItem]
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


class SalesService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.sales = SaleRepo(session, ctx.tenant_id)
        self.sale_lines = SaleLineRepo(session, ctx.tenant_id)
        self.returns = ReturnRepo(session, ctx.tenant_id)
        self.ledger = LedgerService(session, ctx.tenant_id, ctx.user_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ create

    def create(self, body: SaleCreate, *, idempotency_key: str | None = None) -> SaleOut:
        now = now_utc()
        sold_at = body.sold_at or now
        if sold_at > now + MAX_FUTURE:
            raise invalid("sold_at", "cannot be in the future")
        if sold_at < now - MAX_BACKDATE:
            raise invalid("sold_at", "is too far in the past")
        on = ist_date(sold_at)

        with transaction(self.session):
            # One bill at a time per business: numbers stay in sequence and the duplicate check
            # cannot miss a bill that is being saved at the same moment.
            advisory_lock(self.session, self.ctx.tenant_id, "bill-number")
            products = self._load_products(body.lines)
            if body.bill_no is not None:
                self._require_free_bill_no(body.bill_no)
            self.ledger.lock_products(products)
            plans = self._plan(body.lines, products, on)
            amounts = self._price(plans)
            warnings = self._duplicate_warnings(plans, amounts.total, sold_at)
            if idempotency_key is not None and self._key_already_on_a_sale(idempotency_key):
                # The stored response of the first use has expired, this is a deliberate reuse.
                idempotency_key = None

            sale = self.sales.add(
                Sale(
                    bill_no=body.bill_no
                    or next_number(
                        self.session,
                        self.ctx.tenant_id,
                        Sale.bill_no,
                        Sale.tenant_id,
                        prefix="B",
                        on=on,
                        width=5,
                    ),
                    business_date=on,
                    sold_at=sold_at,
                    payment_mode=body.payment_mode,
                    subtotal=amounts.subtotal,
                    discount_total=amounts.discount_total,
                    tax_total=amounts.tax_total,
                    total=amounts.total,
                    idempotency_key=idempotency_key,
                    source="app",
                    created_by=self.ctx.user_id,
                )
            )
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That bill number is already used.", field="bill_no") from exc

            rows = [
                SaleLine(
                    tenant_id=self.ctx.tenant_id,
                    sale_id=sale.id,
                    product_id=item.product_id,
                    batch_id=item.batch_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount_amount=item.discount,
                    tax_rate_pct=item.tax_pct,
                    line_total=item.line_total,
                    business_date=on,
                )
                for item in amounts.items
            ]
            self.session.add_all(rows)
            self.session.flush()
            try:
                self.ledger.post(
                    [
                        MovementEntry(
                            product_id=row.product_id,
                            batch_id=row.batch_id,
                            movement_type="sale",
                            quantity_delta=-row.quantity,
                            source_type="sale",
                            source_id=str(sale.id),
                            occurred_at=sold_at,
                        )
                        for row in rows
                    ]
                )
            except InsufficientStockError as exc:  # the plan checked, so only a bug lands here
                raise AppError(ErrorCode.INSUFFICIENT_STOCK) from exc

            self.audit.record(
                AuditAction.SALE_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="sale",
                entity_id=sale.id,
                after={
                    "bill_no": sale.bill_no,
                    "total": sale.total,
                    "lines": len(rows),
                    "payment_mode": sale.payment_mode,
                },
            )
            result = self.get(sale.id)
            result.warnings = warnings
            return result

    def _load_products(self, lines: list[SaleLineIn]) -> dict[uuid.UUID, tuple[Product, Decimal]]:
        ids = {line.product_id for line in lines}
        rows = self.session.execute(
            select(Product, TaxRate.rate_pct)
            .join(TaxRate, TaxRate.id == Product.tax_rate_id)
            .where(Product.tenant_id == self.ctx.tenant_id, Product.id.in_(ids))
        ).all()
        found = {product.id: (product, pct) for product, pct in rows}
        for index, line in enumerate(lines):
            entry = found.get(line.product_id)
            if entry is None:
                raise not_found("product", field=f"lines[{index}].product_id")
            if not entry[0].is_active:
                raise invalid(
                    f"lines[{index}].product_id",
                    "is not for sale",
                    f"{entry[0].name} is switched off. Switch it on to sell it.",
                )
        return found

    def _key_already_on_a_sale(self, key: str) -> bool:
        return (
            self.session.execute(
                self.sales.select_().where(Sale.idempotency_key == key).limit(1)
            ).first()
            is not None
        )

    def _require_free_bill_no(self, bill_no: str) -> None:
        taken = self.session.execute(
            self.sales.select_().where(Sale.bill_no == bill_no).limit(1)
        ).first()
        if taken is not None:
            raise conflict("That bill number is already used.", field="bill_no")

    def _plan(
        self,
        lines: list[SaleLineIn],
        products: dict[uuid.UUID, tuple[Product, Decimal]],
        on: date,
    ) -> list[LinePlan]:
        """Choose batches for every line. Raises when stock, batch or price rules are broken."""
        available: dict[BalanceKey, Decimal] = {}
        batches: dict[uuid.UUID, list[ProductBatch]] = {}
        for pid, (product, _) in products.items():
            for balance in self.ledger.product_balances(pid):
                available[(pid, balance.batch_id)] = balance.on_hand
            if product.is_batch_tracked:
                batches[pid] = list(
                    self.session.execute(
                        select(ProductBatch).where(
                            ProductBatch.tenant_id == self.ctx.tenant_id,
                            ProductBatch.product_id == pid,
                        )
                    ).scalars()
                )

        plans: list[LinePlan] = []
        shortages: list[Shortage] = []
        for index, line in enumerate(lines):
            product, tax_pct = products[line.product_id]
            unit_price = line.unit_price if line.unit_price is not None else product.selling_price
            if unit_price > product.mrp:
                raise invalid(
                    f"lines[{index}].unit_price",
                    "cannot be above the MRP",
                    f"The price for {product.name} cannot be above its MRP.",
                )
            plan = LinePlan(index, line, product, tax_pct, unit_price)
            plans.append(plan)
            need = line.quantity

            if not product.is_batch_tracked:
                if line.batch_id is not None:
                    raise invalid(
                        f"lines[{index}].batch_id", "this product is not tracked by batch"
                    )
                have = available.get((product.id, None), ZERO)
                if have < need:
                    shortages.append(Shortage(index, product, need, have))
                    continue
                available[(product.id, None)] = have - need
                plan.parts = [(None, need)]
                continue

            stocks = [
                BatchStock(
                    b.id,
                    b.batch_no,
                    b.expiry_date,
                    available.get((product.id, b.id), ZERO),
                    b.status,
                )
                for b in batches[product.id]
            ]
            if line.batch_id is not None:
                chosen = next((s for s in stocks if s.batch_id == line.batch_id), None)
                if chosen is None:
                    raise not_found("batch", field=f"lines[{index}].batch_id")
                problem = batch_problem(chosen, need, on)
                if problem == "expired":
                    raise AppError(
                        ErrorCode.BATCH_EXPIRED,
                        f"Batch {chosen.batch_no} of {product.name} has expired.",
                        details=[ErrorDetail(field=f"lines[{index}].batch_id", issue="expired")],
                    )
                if problem == "unavailable":
                    raise conflict(
                        f"Batch {chosen.batch_no} of {product.name} is on hold and cannot be sold.",
                        field=f"lines[{index}].batch_id",
                    )
                if problem == "short":
                    shortages.append(Shortage(index, product, need, chosen.on_hand))
                    continue
                parts = [(chosen.batch_id, need)]
            else:
                allocation = allocate_fefo(stocks, need, on)
                if not allocation.complete:
                    shortages.append(Shortage(index, product, need, need - allocation.shortfall))
                    continue
                parts = list(allocation.parts)
            for batch_id, take in parts:
                available[(product.id, batch_id)] -= take
            plan.parts = parts

        if shortages:
            raise self._shortage_error(shortages)
        return plans

    @staticmethod
    def _shortage_error(shortages: list[Shortage]) -> AppError:
        names = ", ".join(
            f"{s.product.name} ({fmt_qty(s.have)} left)" for s in shortages[:MAX_SHORT_NAMES]
        )
        extra = len(shortages) - MAX_SHORT_NAMES
        more = f" and {extra} more" if extra > 0 else ""
        return AppError(
            ErrorCode.INSUFFICIENT_STOCK,
            f"Not enough stock for {names}{more}. Lower the quantity or record a delivery first.",
            details=[
                ErrorDetail(
                    field=f"lines[{s.index}].quantity",
                    issue=f"only {fmt_qty(s.have)} available, {fmt_qty(s.needed)} asked for",
                )
                for s in shortages
            ],
        )

    # ------------------------------------------------------------------ pricing

    def _price(self, plans: list[LinePlan]) -> PricedBill:
        items: list[PricedItem] = []
        for plan in plans:
            grosses = [gross_amount(q, plan.unit_price) for _, q in plan.parts]
            discount = plan.request.discount_amount
            if discount > sum(grosses, ZERO):
                raise invalid(
                    f"lines[{plan.index}].discount_amount",
                    "cannot be more than the line amount",
                    f"The discount on {plan.product.name} is more than the line amount.",
                )
            shares = split_discount(discount, grosses)
            for (batch_id, quantity), gross, share in zip(plan.parts, grosses, shares, strict=True):
                items.append(
                    PricedItem(
                        product_id=plan.product.id,
                        batch_id=batch_id,
                        quantity=quantity,
                        unit_price=plan.unit_price,
                        discount=share,
                        tax_pct=plan.tax_pct,
                        gross=gross,
                        line_total=gross - share,
                    )
                )
        subtotal = sum((i.gross for i in items), ZERO)
        discount_total = sum((i.discount for i in items), ZERO)
        tax_total = sum((tax_contained(i.line_total, i.tax_pct) for i in items), ZERO)
        return PricedBill(
            items=items,
            subtotal=subtotal,
            discount_total=discount_total,
            tax_total=tax_total,
            total=subtotal - discount_total,
        )

    def _duplicate_warnings(
        self, plans: list[LinePlan], total: Decimal, sold_at: datetime
    ) -> list[SaleWarning]:
        """Warn (never refuse) when an identical basket with the same total was saved within
        two minutes: a double click or a retry that lost its idempotency key."""
        basket: dict[uuid.UUID, Decimal] = {}
        for plan in plans:
            basket[plan.product.id] = basket.get(plan.product.id, ZERO) + plan.request.quantity
        candidates = self.session.execute(
            self.sales.select_()
            .where(
                Sale.status == "completed",
                Sale.total == total,
                Sale.sold_at.between(sold_at - DUPLICATE_WINDOW, sold_at + DUPLICATE_WINDOW),
            )
            .order_by(Sale.sold_at.desc())
            .limit(5)
        ).scalars()
        for candidate in candidates:
            rows = self.session.execute(
                select(SaleLine.product_id, func.sum(SaleLine.quantity))
                .where(SaleLine.tenant_id == self.ctx.tenant_id, SaleLine.sale_id == candidate.id)
                .group_by(SaleLine.product_id)
            ).all()
            if dict(rows) == basket:
                return [
                    SaleWarning(
                        code="POSSIBLE_DUPLICATE",
                        message=(
                            f"A bill with the same items and total ({candidate.bill_no}) was "
                            "saved a moment ago."
                        ),
                        sale_id=candidate.id,
                    )
                ]
        return []

    # ------------------------------------------------------------------ read

    def get(self, sale_id: uuid.UUID) -> SaleOut:
        sale = self.sales.get(sale_id)
        if sale is None:
            raise not_found("bill")
        line_rows = self.session.execute(
            select(
                SaleLine, Product.sku, Product.name, ProductBatch.batch_no, ProductBatch.expiry_date
            )
            .join(
                Product,
                and_(Product.tenant_id == SaleLine.tenant_id, Product.id == SaleLine.product_id),
            )
            .outerjoin(
                ProductBatch,
                and_(
                    ProductBatch.tenant_id == SaleLine.tenant_id,
                    ProductBatch.id == SaleLine.batch_id,
                ),
            )
            .where(SaleLine.tenant_id == self.ctx.tenant_id, SaleLine.sale_id == sale.id)
            .order_by(SaleLine.id)
        ).all()
        lines = [
            SaleLineOut(
                id=line.id,
                product_id=line.product_id,
                product_sku=sku,
                product_name=name,
                batch_id=line.batch_id,
                batch_no=batch_no,
                expiry_date=expiry,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=line.discount_amount,
                tax_rate_pct=line.tax_rate_pct,
                tax_amount=tax_contained(line.line_total, line.tax_rate_pct),
                line_total=line.line_total,
                returned_qty=line.returned_qty,
            )
            for line, sku, name, batch_no, expiry in line_rows
        ]
        return SaleOut(
            id=sale.id,
            bill_no=sale.bill_no,
            business_date=sale.business_date,
            sold_at=sale.sold_at,
            payment_mode=sale.payment_mode,  # type: ignore[arg-type]
            status=sale.status,  # type: ignore[arg-type]
            subtotal=sale.subtotal,
            discount_total=sale.discount_total,
            tax_total=sale.tax_total,
            total=sale.total,
            void_reason=sale.void_reason,
            voided_at=sale.voided_at,
            source=sale.source,
            created_at=sale.created_at,
            lines=lines,
            returns=self._returns_of(sale),
        )

    def _returns_of(self, sale: Sale) -> list[ReturnOut]:
        headers = list(
            self.session.execute(
                self.returns.select_()
                .where(SaleReturn.sale_id == sale.id)
                .order_by(SaleReturn.created_at, SaleReturn.return_no)
            ).scalars()
        )
        if not headers:
            return []
        rows = self.session.execute(
            select(SaleReturnLine, Product.name)
            .join(
                Product,
                and_(
                    Product.tenant_id == SaleReturnLine.tenant_id,
                    Product.id == SaleReturnLine.product_id,
                ),
            )
            .where(
                SaleReturnLine.tenant_id == self.ctx.tenant_id,
                SaleReturnLine.return_id.in_([h.id for h in headers]),
            )
            .order_by(SaleReturnLine.id)
        ).all()
        by_return: dict[uuid.UUID, list[ReturnLineOut]] = {}
        for line, name in rows:
            by_return.setdefault(line.return_id, []).append(
                ReturnLineOut(
                    id=line.id,
                    sale_line_id=line.sale_line_id,
                    product_id=line.product_id,
                    product_name=name,
                    batch_id=line.batch_id,
                    quantity=line.quantity,
                    refund_amount=line.refund_amount,
                    disposition=line.disposition,  # type: ignore[arg-type]
                )
            )
        return [
            ReturnOut(
                id=h.id,
                sale_id=h.sale_id,
                bill_no=sale.bill_no,
                return_no=h.return_no,
                business_date=h.business_date,
                reason=h.reason,
                status=h.status,  # type: ignore[arg-type]
                refund_total=h.refund_total,
                created_at=h.created_at,
                lines=by_return.get(h.id, []),
            )
            for h in headers
        ]

    def search(
        self,
        *,
        page: PageParams,
        start: date | None,
        end: date | None,
        q: str | None,
        status: str | None,
        sort: str | None,
    ) -> tuple[list[SaleListItem], int]:
        counts = (
            select(SaleLine.sale_id.label("sale_id"), func.count().label("n"))
            .where(SaleLine.tenant_id == self.ctx.tenant_id)
            .group_by(SaleLine.sale_id)
            .subquery()
        )
        refunds = (
            select(
                SaleReturn.sale_id.label("sale_id"), func.sum(SaleReturn.refund_total).label("r")
            )
            .where(SaleReturn.tenant_id == self.ctx.tenant_id, SaleReturn.status == "posted")
            .group_by(SaleReturn.sale_id)
            .subquery()
        )
        stmt = (
            self.sales.select_()
            .add_columns(func.coalesce(counts.c.n, 0), func.coalesce(refunds.c.r, ZERO))
            .outerjoin(counts, counts.c.sale_id == Sale.id)
            .outerjoin(refunds, refunds.c.sale_id == Sale.id)
        )
        if start is not None:
            stmt = stmt.where(Sale.business_date >= start)
        if end is not None:
            stmt = stmt.where(Sale.business_date <= end)
        if status is not None:
            stmt = stmt.where(Sale.status == status)
        term = (q or "").strip()
        if term:
            stmt = stmt.where(Sale.bill_no.ilike(f"%{escape_like(term)}%", escape="\\"))
        order = parse_sort(
            sort,
            {"sold_at": Sale.sold_at, "bill_no": Sale.bill_no, "total": Sale.total},
            "sold_at:desc",
        )
        rows, total = paginate(self.session, stmt.order_by(*order, Sale.id), page)
        items = [
            SaleListItem(
                id=sale.id,
                bill_no=sale.bill_no,
                business_date=sale.business_date,
                sold_at=sale.sold_at,
                payment_mode=sale.payment_mode,  # type: ignore[arg-type]
                status=sale.status,  # type: ignore[arg-type]
                items=int(n),
                total=sale.total,
                returned_total=returned,
            )
            for sale, n, returned in rows
        ]
        return items, total

    def summary(self, *, start: date | None, end: date | None, group: str) -> SalesSummary:
        def period(column: Any) -> Any:
            if group == "week":
                return func.date_trunc("week", column).cast(Sale.business_date.type)
            return column

        sale_period = period(Sale.business_date).label("period")
        sales_rows = self.session.execute(
            select(
                sale_period,
                func.count().label("bills"),
                func.coalesce(func.sum(Sale.total), ZERO),
                func.coalesce(func.sum(Sale.discount_total), ZERO),
            )
            .where(Sale.tenant_id == self.ctx.tenant_id, Sale.status == "completed")
            .where(*self._range(Sale.business_date, start, end))
            .group_by(sale_period)
        ).all()
        return_period = period(SaleReturn.business_date).label("period")
        return_rows = self.session.execute(
            select(return_period, func.coalesce(func.sum(SaleReturn.refund_total), ZERO))
            .where(SaleReturn.tenant_id == self.ctx.tenant_id, SaleReturn.status == "posted")
            .where(*self._range(SaleReturn.business_date, start, end))
            .group_by(return_period)
        ).all()
        points: dict[date, dict[str, Decimal | int]] = {}
        for day, bills, sales, discounts in sales_rows:
            points[day] = {
                "bills": int(bills),
                "sales": sales,
                "discounts": discounts,
                "returns": ZERO,
            }
        for day, refunded in return_rows:
            point = points.setdefault(
                day, {"bills": 0, "sales": ZERO, "discounts": ZERO, "returns": ZERO}
            )
            point["returns"] = refunded
        series = [
            SalesPoint(
                period=day,
                bills=int(v["bills"]),
                sales=Decimal(v["sales"]),
                returns=Decimal(v["returns"]),
                discounts=Decimal(v["discounts"]),
            )
            for day, v in sorted(points.items())
        ]
        return SalesSummary(
            group=group,  # type: ignore[arg-type]
            bills=sum(p.bills for p in series),
            sales=sum((p.sales for p in series), ZERO),
            returns=sum((p.returns for p in series), ZERO),
            discounts=sum((p.discounts for p in series), ZERO),
            series=series,
        )

    @staticmethod
    def _range(column: Any, start: date | None, end: date | None) -> list[Any]:
        conditions: list[Any] = []
        if start is not None:
            conditions.append(column >= start)
        if end is not None:
            conditions.append(column <= end)
        return conditions

    # ------------------------------------------------------------------ void

    def void(self, sale_id: uuid.UUID, reason: str) -> SaleOut:
        """Cancel a whole bill: new reversing movements, the original rows stay as they are."""
        with transaction(self.session):
            sale = self.session.execute(
                self.sales.select_().where(Sale.id == sale_id).with_for_update()
            ).scalar_one_or_none()
            if sale is None:
                raise not_found("bill")
            if sale.status == "void":
                raise conflict("This bill is already void.")
            has_returns = self.session.execute(
                self.returns.select_()
                .where(SaleReturn.sale_id == sale.id, SaleReturn.status == "posted")
                .limit(1)
            ).first()
            if has_returns is not None:
                raise conflict("This bill has returns, so it cannot be voided.")

            originals = self.ledger.movements_for("sale", str(sale.id), movement_type="sale")
            self.ledger.lock_products({m.product_id for m in originals})
            now = now_utc()
            self.ledger.post(
                [
                    MovementEntry(
                        product_id=m.product_id,
                        batch_id=m.batch_id,
                        movement_type="void_reversal",
                        quantity_delta=-m.quantity_delta,
                        source_type="void",
                        source_id=str(sale.id),
                        unit_cost=m.unit_cost,
                        reverses_movement_id=m.id,
                        reason_code="void",
                        note=reason,
                        occurred_at=now,
                    )
                    for m in originals
                ]
            )
            sale.status = "void"
            sale.void_reason = reason
            sale.voided_at = now
            sale.voided_by = self.ctx.user_id
            self.session.flush()
            self.audit.record(
                AuditAction.SALE_VOID,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="sale",
                entity_id=sale.id,
                before={"status": "completed"},
                after={"status": "void", "reason": reason, "total": sale.total},
            )
            return self.get(sale.id)

    # ------------------------------------------------------------------ returns

    def create_return(self, sale_id: uuid.UUID, body: ReturnCreate) -> ReturnOut:
        """Take goods back against a bill. Restocked goods go back on the shelf, damaged and
        expired goods come in and are written off in the same step."""
        with transaction(self.session):
            sale = self.session.execute(
                self.sales.select_().where(Sale.id == sale_id).with_for_update()
            ).scalar_one_or_none()
            if sale is None:
                raise not_found("bill")
            if sale.status != "completed":
                raise conflict("A void bill cannot take returns.")

            lines = {
                line.id: line
                for line in self.session.execute(
                    self.sale_lines.select_().where(SaleLine.sale_id == sale.id).with_for_update()
                ).scalars()
            }
            wanted: dict[int, Decimal] = {}
            for index, item in enumerate(body.lines):
                if item.sale_line_id not in lines:
                    raise not_found("bill line", field=f"lines[{index}].sale_line_id")
                wanted[item.sale_line_id] = wanted.get(item.sale_line_id, ZERO) + item.quantity
            over = [
                ErrorDetail(
                    field="lines",
                    issue=(
                        f"line {line_id}: {fmt_qty(qty)} asked for, "
                        f"{fmt_qty(lines[line_id].quantity - lines[line_id].returned_qty)} "
                        "can still come back"
                    ),
                )
                for line_id, qty in wanted.items()
                if qty > lines[line_id].quantity - lines[line_id].returned_qty
            ]
            if over:
                raise AppError(ErrorCode.RETURN_EXCEEDS_SOLD, details=over)

            costs = {
                (m.product_id, m.batch_id): m.unit_cost
                for m in reversed(
                    self.ledger.movements_for("sale", str(sale.id), movement_type="sale")
                )
            }
            self.ledger.lock_products({line.product_id for line in lines.values()})
            today = today_ist()
            advisory_lock(self.session, self.ctx.tenant_id, "return-number")
            header = self.returns.add(
                SaleReturn(
                    sale_id=sale.id,
                    return_no=next_number(
                        self.session,
                        self.ctx.tenant_id,
                        SaleReturn.return_no,
                        SaleReturn.tenant_id,
                        prefix="R",
                        on=today,
                        width=4,
                    ),
                    business_date=today,
                    reason=body.reason,
                    refund_total=ZERO,
                )
            )
            self.session.flush()

            now = now_utc()
            entries: list[MovementEntry] = []
            rows: list[SaleReturnLine] = []
            returned_so_far = {line_id: line.returned_qty for line_id, line in lines.items()}
            refund_total = ZERO
            for item in body.lines:
                line = lines[item.sale_line_id]
                refund = refund_for(
                    line.line_total, line.quantity, returned_so_far[line.id], item.quantity
                )
                returned_so_far[line.id] += item.quantity
                refund_total += refund
                rows.append(
                    SaleReturnLine(
                        tenant_id=self.ctx.tenant_id,
                        return_id=header.id,
                        sale_line_id=line.id,
                        product_id=line.product_id,
                        batch_id=line.batch_id,
                        quantity=item.quantity,
                        refund_amount=refund,
                        disposition=item.disposition,
                    )
                )
                cost = costs.get((line.product_id, line.batch_id))
                common = {
                    "product_id": line.product_id,
                    "batch_id": line.batch_id,
                    "source_type": "sale_return",
                    "source_id": str(header.id),
                    "unit_cost": cost,
                    "occurred_at": now,
                }
                entries.append(
                    MovementEntry(
                        movement_type="return_in",
                        quantity_delta=item.quantity,
                        reason_code=item.disposition,
                        note=body.reason,
                        **common,  # type: ignore[arg-type]
                    )
                )
                if item.disposition != "restock":
                    entries.append(
                        MovementEntry(
                            movement_type=(
                                "damage" if item.disposition == "damaged" else "expiry_writeoff"
                            ),
                            quantity_delta=-item.quantity,
                            reason_code="return",
                            note=body.reason,
                            **common,  # type: ignore[arg-type]
                        )
                    )
            self.session.add_all(rows)
            for line_id, total in returned_so_far.items():
                lines[line_id].returned_qty = total
            header.refund_total = refund_total
            self.session.flush()
            self.ledger.post(entries)
            self.audit.record(
                AuditAction.RETURN_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="sale_return",
                entity_id=header.id,
                after={
                    "return_no": header.return_no,
                    "bill_no": sale.bill_no,
                    "refund_total": refund_total,
                    "lines": len(rows),
                },
            )
            created = next(r for r in self._returns_of(sale) if r.id == header.id)
            return created
