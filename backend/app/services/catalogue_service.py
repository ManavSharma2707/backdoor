"""Categories, products, price history, equivalents and tax rates."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.audit import AuditAction, AuditService, changed_fields
from app.core.clock import today_ist
from app.core.db import transaction
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.pagination import PageParams, paginate, parse_sort
from app.core.repo import TenantRepo
from app.models.catalogue import Category, Product, ProductEquivalent, ProductPrice
from app.models.inventory import InventoryMovement, StockBalance
from app.models.reference import TaxRate
from app.models.suppliers import Supplier, SupplierProductTerm
from app.models.tenancy import Tenant
from app.schemas.catalogue import (
    MEDICINE_FIELDS,
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    EquivalentCreate,
    EquivalentOut,
    ProductCreate,
    ProductOut,
    ProductPatch,
    ProductStatus,
    TaxRateOut,
)
from app.schemas.common import ErrorDetail
from app.services.common import conflict, escape_like, invalid, not_found, slugify

ZERO = Decimal(0)

PRODUCT_AUDIT_FIELDS = (
    "sku",
    "barcode",
    "name",
    "brand",
    "category_id",
    "base_unit",
    "pack_label",
    "tax_rate_id",
    "is_batch_tracked",
    "shelf_life_days",
    "schedule_class",
    "generic_name",
    "strength",
    "dosage_form",
    "manufacturer",
    "min_stock_qty",
    "is_seasonal",
    "launched_on",
    "notes",
)
PRICE_FIELDS = ("mrp", "selling_price")


class CategoryRepo(TenantRepo[Category]):
    model = Category


class ProductRepo(TenantRepo[Product]):
    model = Product


class PriceRepo(TenantRepo[ProductPrice]):
    model = ProductPrice


class EquivalentRepo(TenantRepo[ProductEquivalent]):
    model = ProductEquivalent


class SupplierRepo(TenantRepo[Supplier]):
    model = Supplier


class TermRepo(TenantRepo[SupplierProductTerm]):
    model = SupplierProductTerm


# --------------------------------------------------------------------------- categories


class CategoryService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.repo = CategoryRepo(session, ctx.tenant_id)
        self.audit = AuditService(session)

    def list_all(self) -> list[CategoryOut]:
        counts = (
            select(Product.category_id.label("category_id"), func.count().label("n"))
            .where(Product.tenant_id == self.ctx.tenant_id, Product.is_active.is_(True))
            .group_by(Product.category_id)
            .subquery()
        )
        rows = self.session.execute(
            self.repo.select_()
            .add_columns(func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.category_id == Category.id)
            .order_by(Category.position, Category.name)
        ).all()
        return [self._out(category, int(count)) for category, count in rows]

    def create(self, body: CategoryCreate) -> CategoryOut:
        with transaction(self.session):
            if body.parent_id is not None:
                self._require_top_level(body.parent_id)
            category = self.repo.add(
                Category(
                    name=body.name,
                    slug=self._free_slug(body.name),
                    parent_id=body.parent_id,
                    position=body.position,
                )
            )
            self.session.flush()
            self._audit(AuditAction.CATEGORY_CREATE, category, after={"name": category.name})
            return self._out(category, 0)

    def update(self, category_id: uuid.UUID, body: CategoryPatch) -> CategoryOut:
        with transaction(self.session):
            category = self.repo.get(category_id)
            if category is None:
                raise not_found("category")
            before = {
                "name": category.name,
                "parent_id": category.parent_id,
                "position": category.position,
                "is_active": category.is_active,
            }
            if "parent_id" in body.model_fields_set and body.parent_id != category.parent_id:
                if body.parent_id is not None:
                    self._check_parent(category, body.parent_id)
                category.parent_id = body.parent_id
            for name in ("name", "position", "is_active"):
                if name in body.model_fields_set:
                    setattr(category, name, getattr(body, name))
            self.session.flush()
            after = {
                "name": category.name,
                "parent_id": category.parent_id,
                "position": category.position,
                "is_active": category.is_active,
            }
            old, new = changed_fields(before, after)
            if new:
                self._audit(AuditAction.CATEGORY_UPDATE, category, before=old, after=new)
            count = self.session.execute(
                select(func.count()).where(
                    Product.tenant_id == self.ctx.tenant_id,
                    Product.category_id == category.id,
                    Product.is_active.is_(True),
                )
            ).scalar_one()
            return self._out(category, int(count))

    def _check_parent(self, category: Category, parent_id: uuid.UUID) -> None:
        if parent_id == category.id:
            raise invalid("parent_id", "a category cannot be its own parent")
        has_children = self.session.execute(
            select(func.count()).where(
                Category.tenant_id == self.ctx.tenant_id, Category.parent_id == category.id
            )
        ).scalar_one()
        if has_children:
            raise invalid("parent_id", "a category with sub categories stays at the top level")
        self._require_top_level(parent_id)

    def _require_top_level(self, parent_id: uuid.UUID) -> Category:
        parent = self.repo.get(parent_id)
        if parent is None:
            raise not_found("category", field="parent_id")
        if parent.parent_id is not None:
            raise invalid("parent_id", "categories have two levels at most")
        return parent

    def _free_slug(self, name: str) -> str:
        base = slugify(name, fallback="category")
        slug, n = base, 1
        while self.session.execute(
            select(Category.id).where(
                Category.tenant_id == self.ctx.tenant_id, Category.slug == slug
            )
        ).first():
            n += 1
            slug = f"{base}-{n}"
        return slug

    def _audit(
        self,
        action: AuditAction,
        category: Category,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self.audit.record(
            action,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="category",
            entity_id=category.id,
            before=before,
            after=after,
        )

    @staticmethod
    def _out(category: Category, product_count: int) -> CategoryOut:
        return CategoryOut(
            id=category.id,
            parent_id=category.parent_id,
            name=category.name,
            slug=category.slug,
            position=category.position,
            is_active=category.is_active,
            product_count=product_count,
        )


# --------------------------------------------------------------------------- products


class ProductService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.products = ProductRepo(session, ctx.tenant_id)
        self.categories = CategoryRepo(session, ctx.tenant_id)
        self.prices = PriceRepo(session, ctx.tenant_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ reads

    def _stock_subquery(self) -> Any:
        return (
            select(
                StockBalance.product_id.label("product_id"),
                func.sum(StockBalance.on_hand).label("on_hand"),
            )
            .where(StockBalance.tenant_id == self.ctx.tenant_id)
            .group_by(StockBalance.product_id)
            .subquery()
        )

    def _detail_query(self) -> Any:
        stock = self._stock_subquery()
        primary = (
            select(
                SupplierProductTerm.product_id.label("product_id"),
                SupplierProductTerm.supplier_id.label("supplier_id"),
            )
            .where(
                SupplierProductTerm.tenant_id == self.ctx.tenant_id,
                SupplierProductTerm.is_primary.is_(True),
                SupplierProductTerm.effective_to.is_(None),
            )
            .subquery()
        )
        query = (
            self.products.select_()
            .add_columns(
                Category.name.label("category_name"),
                TaxRate.code.label("tax_rate_code"),
                TaxRate.rate_pct.label("tax_rate_pct"),
                func.coalesce(stock.c.on_hand, ZERO).label("on_hand"),
                Supplier.id.label("supplier_id"),
                Supplier.name.label("supplier_name"),
            )
            .join(
                Category,
                and_(Category.tenant_id == Product.tenant_id, Category.id == Product.category_id),
            )
            .join(TaxRate, TaxRate.id == Product.tax_rate_id)
            .outerjoin(stock, stock.c.product_id == Product.id)
            .outerjoin(primary, primary.c.product_id == Product.id)
            .outerjoin(
                Supplier,
                and_(Supplier.tenant_id == Product.tenant_id, Supplier.id == primary.c.supplier_id),
            )
        )
        return query, stock

    @staticmethod
    def _out(row: Any) -> ProductOut:
        product = row[0]
        data = {c.name: getattr(product, c.name) for c in Product.__table__.columns}
        return ProductOut(
            **data,
            category_name=row.category_name,
            tax_rate_code=row.tax_rate_code,
            tax_rate_pct=row.tax_rate_pct,
            on_hand=row.on_hand,
            primary_supplier_id=row.supplier_id,
            primary_supplier_name=row.supplier_name,
        )

    def get(self, product_id: uuid.UUID) -> ProductOut:
        query, _ = self._detail_query()
        row = self.session.execute(query.where(Product.id == product_id)).first()
        if row is None:
            raise not_found("product")
        return self._out(row)

    def search(
        self,
        *,
        page: PageParams,
        q: str | None,
        category_id: uuid.UUID | None,
        status: ProductStatus,
        supplier_id: uuid.UUID | None,
        batch_tracked: bool | None,
        sort: str | None,
    ) -> tuple[list[ProductOut], int]:
        query, stock = self._detail_query()
        if status != "all":
            query = query.where(Product.is_active.is_(status == "active"))
        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        if batch_tracked is not None:
            query = query.where(Product.is_batch_tracked.is_(batch_tracked))
        if supplier_id is not None:
            supplied = select(SupplierProductTerm.product_id).where(
                SupplierProductTerm.tenant_id == self.ctx.tenant_id,
                SupplierProductTerm.supplier_id == supplier_id,
                SupplierProductTerm.effective_to.is_(None),
            )
            query = query.where(Product.id.in_(supplied))

        order: list[ColumnElement[Any]] = []
        term = (q or "").strip()
        if term:
            like = f"%{escape_like(term)}%"
            query = query.where(
                or_(
                    Product.name.ilike(like, escape="\\"),
                    Product.sku.ilike(like, escape="\\"),
                    Product.brand.ilike(like, escape="\\"),
                    Product.generic_name.ilike(like, escape="\\"),
                    Product.barcode == term,
                )
            )
            exact = case(
                (func.lower(Product.sku) == term.lower(), 0),
                (Product.barcode == term, 0),
                (Product.name.ilike(f"{escape_like(term)}%", escape="\\"), 1),
                else_=2,
            )
            order = [exact, func.similarity(Product.name, term).desc()]
        allowed: dict[str, ColumnElement[Any]] = {
            "name": func.lower(Product.name),
            "sku": Product.sku,
            "selling_price": Product.selling_price,
            "created_at": Product.created_at,
            "on_hand": func.coalesce(stock.c.on_hand, ZERO),
        }
        order += parse_sort(sort, allowed, "name:asc")
        rows, total = paginate(self.session, query.order_by(*order, Product.id), page)
        return [self._out(row) for row in rows], total

    def price_history(self, product_id: uuid.UUID) -> list[ProductPrice]:
        if self.products.get(product_id) is None:
            raise not_found("product")
        stmt = (
            self.prices.select_()
            .where(ProductPrice.product_id == product_id)
            .order_by(ProductPrice.effective_from.desc())
        )
        return list(self.session.execute(stmt).scalars())

    # ------------------------------------------------------------------ writes

    def create(self, body: ProductCreate) -> ProductOut:
        with transaction(self.session):
            self._require_category(body.category_id)
            self._require_tax_rate(body.tax_rate_id)
            self._check_medicine_fields(body.model_dump(include=set(MEDICINE_FIELDS)))
            self._check_unique(sku=body.sku, barcode=body.barcode, exclude=None)
            product = self.products.add(Product(**body.model_dump()))
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That SKU is already used by another product.", field="sku") from exc
            self.prices.add(
                ProductPrice(
                    product_id=product.id,
                    mrp=product.mrp,
                    selling_price=product.selling_price,
                    effective_from=today_ist(),
                    reason="Opening price",
                )
            )
            self.session.flush()
            self.audit.record(
                AuditAction.PRODUCT_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="product",
                entity_id=product.id,
                after={
                    "sku": product.sku,
                    "name": product.name,
                    "category_id": product.category_id,
                },
            )
            return self.get(product.id)

    def update(self, product_id: uuid.UUID, body: ProductPatch) -> ProductOut:
        with transaction(self.session):
            product = self._locked(product_id)
            sent = body.model_fields_set - {"price_change_reason"}
            before = {
                name: getattr(product, name) for name in (*PRODUCT_AUDIT_FIELDS, *PRICE_FIELDS)
            }

            if body.category_id is not None and body.category_id != product.category_id:
                self._require_category(body.category_id)
            if body.tax_rate_id is not None and body.tax_rate_id != product.tax_rate_id:
                self._require_tax_rate(body.tax_rate_id)
            if "sku" in sent or "barcode" in sent:
                self._check_unique(
                    sku=body.sku if "sku" in sent else None,
                    barcode=body.barcode if "barcode" in sent else None,
                    exclude=product.id,
                )
            if (
                "is_batch_tracked" in sent
                and body.is_batch_tracked != product.is_batch_tracked
                and self._has_history(product.id)
            ):
                raise conflict(
                    "This product already has stock history, so batch tracking cannot be changed.",
                    field="is_batch_tracked",
                )
            self._check_medicine_fields({n: getattr(body, n) for n in MEDICINE_FIELDS if n in sent})

            for name in sent:
                setattr(product, name, getattr(body, name))
            if product.selling_price > product.mrp:
                raise invalid("selling_price", "cannot be above the MRP")
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That SKU is already used by another product.", field="sku") from exc

            prices_changed = any(before[name] != getattr(product, name) for name in PRICE_FIELDS)
            if prices_changed:
                self._record_price_change(product, body.price_change_reason)
            after = {
                name: getattr(product, name) for name in (*PRODUCT_AUDIT_FIELDS, *PRICE_FIELDS)
            }
            old, new = changed_fields(before, after)
            other_old = {k: v for k, v in old.items() if k not in PRICE_FIELDS}
            other_new = {k: v for k, v in new.items() if k not in PRICE_FIELDS}
            self._audit(AuditAction.PRODUCT_UPDATE, product, other_old, other_new)
            if prices_changed:
                self._audit(
                    AuditAction.PRODUCT_PRICE_CHANGE,
                    product,
                    {k: before[k] for k in PRICE_FIELDS},
                    {k: after[k] for k in PRICE_FIELDS},
                )
            return self.get(product.id)

    def set_active(self, product_id: uuid.UUID, *, active: bool) -> ProductOut:
        with transaction(self.session):
            product = self._locked(product_id)
            if product.is_active != active:
                product.is_active = active
                self.session.flush()
                self._audit(
                    AuditAction.PRODUCT_ACTIVATE if active else AuditAction.PRODUCT_DEACTIVATE,
                    product,
                    {"is_active": not active},
                    {"is_active": active},
                )
            return self.get(product.id)

    # ------------------------------------------------------------------ helpers

    def _locked(self, product_id: uuid.UUID) -> Product:
        row = self.session.execute(
            self.products.select_().where(Product.id == product_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise not_found("product")
        return row

    def _require_category(self, category_id: uuid.UUID) -> Category:
        category = self.categories.get(category_id)
        if category is None:
            raise not_found("category", field="category_id")
        if not category.is_active:
            raise invalid("category_id", "this category is switched off")
        return category

    def _require_tax_rate(self, tax_rate_id: uuid.UUID) -> TaxRate:
        rate = self.session.get(TaxRate, tax_rate_id)
        if rate is None:
            raise not_found("tax rate", field="tax_rate_id")
        return rate

    def _check_medicine_fields(self, values: dict[str, Any]) -> None:
        """Medicine details are descriptive and belong to medical businesses only."""
        given = [name for name, value in values.items() if value is not None]
        if not given:
            return
        business_type = self.session.execute(
            select(Tenant.business_type).where(Tenant.id == self.ctx.tenant_id)
        ).scalar_one()
        if business_type != "medical":
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Medicine details are only for medical businesses.",
                details=[
                    ErrorDetail(field=name, issue="only for medical businesses") for name in given
                ],
            )

    def _check_unique(
        self, *, sku: str | None, barcode: str | None, exclude: uuid.UUID | None
    ) -> None:
        for column, value, field, message in (
            (Product.sku, sku, "sku", "That SKU is already used by another product."),
            (
                Product.barcode,
                barcode,
                "barcode",
                "That barcode is already used by another product.",
            ),
        ):
            if value is None:
                continue
            stmt = self.products.select_().where(column == value)
            if exclude is not None:
                stmt = stmt.where(Product.id != exclude)
            if self.session.execute(stmt.limit(1)).first() is not None:
                raise conflict(message, field=field)

    def _has_history(self, product_id: uuid.UUID) -> bool:
        return (
            self.session.execute(
                select(InventoryMovement.id)
                .where(
                    InventoryMovement.tenant_id == self.ctx.tenant_id,
                    InventoryMovement.product_id == product_id,
                )
                .limit(1)
            ).first()
            is not None
        )

    def _record_price_change(self, product: Product, reason: str | None) -> None:
        """Close the open price row and open a new one. A second change on the same day
        edits that day's row, because history keeps one row per effective date."""
        today = today_ist()
        current = self.session.execute(
            self.prices.select_()
            .where(ProductPrice.product_id == product.id, ProductPrice.effective_to.is_(None))
            .order_by(ProductPrice.effective_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        if current is not None and current.effective_from >= today:
            current.mrp = product.mrp
            current.selling_price = product.selling_price
            current.reason = reason or current.reason
            return
        if current is not None:
            current.effective_to = today - timedelta(days=1)
        self.prices.add(
            ProductPrice(
                product_id=product.id,
                mrp=product.mrp,
                selling_price=product.selling_price,
                effective_from=today,
                reason=reason,
            )
        )
        self.session.flush()

    def _audit(
        self,
        action: AuditAction,
        product: Product,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        if not after:
            return
        self.audit.record(
            action,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="product",
            entity_id=product.id,
            before=before,
            after=after,
        )


# --------------------------------------------------------------------------- equivalents


class EquivalentService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.products = ProductRepo(session, ctx.tenant_id)
        self.links = EquivalentRepo(session, ctx.tenant_id)

    def list_links(self, product_id: uuid.UUID) -> list[EquivalentOut]:
        if self.products.get(product_id) is None:
            raise not_found("product")
        on_hand = (
            select(
                StockBalance.product_id.label("product_id"),
                func.sum(StockBalance.on_hand).label("on_hand"),
            )
            .where(StockBalance.tenant_id == self.ctx.tenant_id)
            .group_by(StockBalance.product_id)
            .subquery()
        )
        rows = self.session.execute(
            self.links.select_()
            .add_columns(Product.sku, Product.name, func.coalesce(on_hand.c.on_hand, ZERO))
            .join(
                Product,
                and_(
                    Product.tenant_id == ProductEquivalent.tenant_id,
                    Product.id == ProductEquivalent.equivalent_product_id,
                ),
            )
            .outerjoin(on_hand, on_hand.c.product_id == Product.id)
            .where(ProductEquivalent.product_id == product_id)
            .order_by(Product.name)
        ).all()
        return [
            EquivalentOut(
                id=link.id,
                equivalent_product_id=link.equivalent_product_id,
                equivalent_sku=sku,
                equivalent_name=name,
                equivalent_on_hand=stock,
                note=link.note,
                created_at=link.created_at,
            )
            for link, sku, name, stock in rows
        ]

    def create(self, product_id: uuid.UUID, body: EquivalentCreate) -> EquivalentOut:
        with transaction(self.session):
            if self.products.get(product_id) is None:
                raise not_found("product")
            if body.equivalent_product_id == product_id:
                raise invalid("equivalent_product_id", "a product cannot be its own equivalent")
            if self.products.get(body.equivalent_product_id) is None:
                raise not_found("product", field="equivalent_product_id")
            exists = self.session.execute(
                self.links.select_()
                .where(
                    ProductEquivalent.product_id == product_id,
                    ProductEquivalent.equivalent_product_id == body.equivalent_product_id,
                )
                .limit(1)
            ).first()
            if exists is not None:
                raise conflict("That equivalent is already linked.", field="equivalent_product_id")
            link = self.links.add(
                ProductEquivalent(
                    product_id=product_id,
                    equivalent_product_id=body.equivalent_product_id,
                    note=body.note,
                    created_by=self.ctx.user_id,
                )
            )
            self.session.flush()
            created = next(item for item in self.list_links(product_id) if item.id == link.id)
            return created

    def delete(self, product_id: uuid.UUID, link_id: uuid.UUID) -> None:
        with transaction(self.session):
            link = self.links.get(link_id)
            if link is None or link.product_id != product_id:
                raise not_found("link")
            self.session.delete(link)
            self.session.flush()


def list_tax_rates(session: Session) -> list[TaxRateOut]:
    """Rates in force today, lowest first. Reference data, the same for every tenant."""
    today = today_ist()
    rows = session.execute(
        select(TaxRate)
        .where(
            TaxRate.effective_from <= today,
            or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= today),
        )
        .order_by(TaxRate.rate_pct)
    ).scalars()
    return [TaxRateOut.model_validate(row) for row in rows]
