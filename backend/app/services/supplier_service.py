"""Suppliers and their effective dated product terms."""

import uuid
from collections.abc import Hashable
from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService, changed_fields
from app.core.clock import today_ist
from app.core.db import transaction
from app.core.deps import TenantContext
from app.core.pagination import PageParams, paginate, parse_sort
from app.engine.lead_time import DEFAULT_LEAD_TIME_DAYS, resolve_lead_time
from app.engine.term_rules import Span, plan_new_span
from app.models.catalogue import Product
from app.models.suppliers import Supplier, SupplierProductTerm
from app.models.tenancy import BusinessSettings
from app.schemas.suppliers import (
    SupplierCreate,
    SupplierOut,
    SupplierPatch,
    TermCreate,
    TermOut,
    TermPatch,
)
from app.services.catalogue_service import ProductRepo, SupplierRepo, TermRepo
from app.services.common import conflict, escape_like, invalid, not_found

SUPPLIER_FIELDS = (
    "code",
    "name",
    "contact_name",
    "phone",
    "email",
    "payment_terms_days",
    "default_lead_time_days",
    "delivery_weekdays",
    "min_order_value",
    "credit_limit",
    "accepts_expiry_returns",
    "expiry_return_window_days",
    "return_window_days",
    "is_active",
    "notes",
)
TERM_FIELDS = (
    "is_primary",
    "purchase_price",
    "pack_size",
    "moq_units",
    "lead_time_days",
    "effective_from",
    "effective_to",
)


def in_force(term: SupplierProductTerm, on: date) -> bool:
    return term.effective_from <= on and (term.effective_to is None or term.effective_to >= on)


def find_term(
    session: Session,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    on: date,
    *,
    supplier_id: uuid.UUID | None = None,
) -> SupplierProductTerm | None:
    """The term in force for a product on `on`: for one supplier when given, else the primary
    one (or, failing that, the most recently started)."""
    stmt = select(SupplierProductTerm).where(
        SupplierProductTerm.tenant_id == tenant_id,
        SupplierProductTerm.product_id == product_id,
        SupplierProductTerm.effective_from <= on,
        or_(SupplierProductTerm.effective_to.is_(None), SupplierProductTerm.effective_to >= on),
    )
    if supplier_id is not None:
        stmt = stmt.where(SupplierProductTerm.supplier_id == supplier_id)
    stmt = stmt.order_by(
        SupplierProductTerm.is_primary.desc(), SupplierProductTerm.effective_from.desc()
    ).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def business_lead_time(session: Session, tenant_id: uuid.UUID) -> int:
    value = session.execute(
        select(BusinessSettings.default_lead_time_days).where(
            BusinessSettings.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    return DEFAULT_LEAD_TIME_DAYS if value is None else int(value)


class SupplierService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.repo = SupplierRepo(session, ctx.tenant_id)
        self.audit = AuditService(session)

    def _terms_in_force(self) -> Any:
        today = today_ist()
        return (
            select(
                SupplierProductTerm.supplier_id.label("supplier_id"),
                func.count().label("n"),
            )
            .where(
                SupplierProductTerm.tenant_id == self.ctx.tenant_id,
                SupplierProductTerm.effective_from <= today,
                or_(
                    SupplierProductTerm.effective_to.is_(None),
                    SupplierProductTerm.effective_to >= today,
                ),
            )
            .group_by(SupplierProductTerm.supplier_id)
            .subquery()
        )

    @staticmethod
    def _out(supplier: Supplier, current_terms: int) -> SupplierOut:
        data = {c.name: getattr(supplier, c.name) for c in Supplier.__table__.columns}
        return SupplierOut(**data, current_terms=current_terms)

    def get(self, supplier_id: uuid.UUID) -> SupplierOut:
        counts = self._terms_in_force()
        row = self.session.execute(
            self.repo.select_()
            .add_columns(func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.supplier_id == Supplier.id)
            .where(Supplier.id == supplier_id)
        ).first()
        if row is None:
            raise not_found("supplier")
        return self._out(row[0], int(row[1]))

    def search(
        self, *, page: PageParams, q: str | None, active: bool | None, sort: str | None
    ) -> tuple[list[SupplierOut], int]:
        counts = self._terms_in_force()
        stmt = (
            self.repo.select_()
            .add_columns(func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.supplier_id == Supplier.id)
        )
        if active is not None:
            stmt = stmt.where(Supplier.is_active.is_(active))
        term = (q or "").strip()
        if term:
            like = f"%{escape_like(term)}%"
            stmt = stmt.where(
                or_(Supplier.name.ilike(like, escape="\\"), Supplier.code.ilike(like, escape="\\"))
            )
        order = parse_sort(
            sort,
            {
                "name": func.lower(Supplier.name),
                "code": Supplier.code,
                "created_at": Supplier.created_at,
            },
            "name:asc",
        )
        rows, total = paginate(self.session, stmt.order_by(*order, Supplier.id), page)
        return [self._out(row[0], int(row[1])) for row in rows], total

    def create(self, body: SupplierCreate) -> SupplierOut:
        with transaction(self.session):
            self._check_code(body.code, exclude=None)
            supplier = self.repo.add(Supplier(**body.model_dump()))
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That supplier code is already used.", field="code") from exc
            self.audit.record(
                AuditAction.SUPPLIER_CREATE,
                tenant_id=self.ctx.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="supplier",
                entity_id=supplier.id,
                after={"code": supplier.code, "name": supplier.name},
            )
            return self._out(supplier, 0)

    def update(self, supplier_id: uuid.UUID, body: SupplierPatch) -> SupplierOut:
        with transaction(self.session):
            supplier = self.session.execute(
                self.repo.select_().where(Supplier.id == supplier_id).with_for_update()
            ).scalar_one_or_none()
            if supplier is None:
                raise not_found("supplier")
            if "code" in body.model_fields_set and body.code is not None:
                self._check_code(body.code, exclude=supplier.id)
            before = {name: getattr(supplier, name) for name in SUPPLIER_FIELDS}
            for name in body.model_fields_set:
                setattr(supplier, name, getattr(body, name))
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That supplier code is already used.", field="code") from exc
            old, new = changed_fields(before, {n: getattr(supplier, n) for n in SUPPLIER_FIELDS})
            if new:
                self.audit.record(
                    AuditAction.SUPPLIER_UPDATE,
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    meta=self.ctx.meta,
                    entity_type="supplier",
                    entity_id=supplier.id,
                    before=old,
                    after=new,
                )
            return self.get(supplier.id)

    def _check_code(self, code: str, *, exclude: uuid.UUID | None) -> None:
        stmt = self.repo.select_().where(Supplier.code == code)
        if exclude is not None:
            stmt = stmt.where(Supplier.id != exclude)
        if self.session.execute(stmt.limit(1)).first() is not None:
            raise conflict("That supplier code is already used.", field="code")


class TermService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.suppliers = SupplierRepo(session, ctx.tenant_id)
        self.products = ProductRepo(session, ctx.tenant_id)
        self.terms = TermRepo(session, ctx.tenant_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ reads

    def _out(
        self, term: SupplierProductTerm, product: Product, supplier: Supplier, business_days: int
    ) -> TermOut:
        lead = resolve_lead_time(
            term.lead_time_days, supplier.default_lead_time_days, business_days
        )
        return TermOut(
            id=term.id,
            supplier_id=term.supplier_id,
            product_id=term.product_id,
            product_sku=product.sku,
            product_name=product.name,
            is_primary=term.is_primary,
            purchase_price=term.purchase_price,
            pack_size=term.pack_size,
            moq_units=term.moq_units,
            lead_time_days=term.lead_time_days,
            lead_time_source=lead.source,
            resolved_lead_time_days=lead.days,
            effective_from=term.effective_from,
            effective_to=term.effective_to,
            in_force=in_force(term, today_ist()),
            created_at=term.created_at,
        )

    def list_terms(self, supplier_id: uuid.UUID, *, current_only: bool) -> list[TermOut]:
        supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise not_found("supplier")
        stmt = (
            self.terms.select_()
            .add_columns(Product)
            .join(
                Product,
                and_(
                    Product.tenant_id == SupplierProductTerm.tenant_id,
                    Product.id == SupplierProductTerm.product_id,
                ),
            )
            .where(SupplierProductTerm.supplier_id == supplier_id)
            .order_by(Product.name, SupplierProductTerm.effective_from.desc())
        )
        if current_only:
            today = today_ist()
            stmt = stmt.where(
                SupplierProductTerm.effective_from <= today,
                or_(
                    SupplierProductTerm.effective_to.is_(None),
                    SupplierProductTerm.effective_to >= today,
                ),
            )
        business_days = business_lead_time(self.session, self.ctx.tenant_id)
        return [
            self._out(term, product, supplier, business_days)
            for term, product in self.session.execute(stmt).all()
        ]

    def get(self, term_id: uuid.UUID) -> TermOut:
        term = self.terms.get(term_id)
        if term is None:
            raise not_found("term")
        return self._single(term)

    def _single(self, term: SupplierProductTerm) -> TermOut:
        product = self.products.get(term.product_id)
        supplier = self.suppliers.get(term.supplier_id)
        if product is None or supplier is None:  # cannot happen: composite keys
            raise not_found("term")
        return self._out(
            term, product, supplier, business_lead_time(self.session, self.ctx.tenant_id)
        )

    # ------------------------------------------------------------------ writes

    def create(self, supplier_id: uuid.UUID, body: TermCreate) -> TermOut:
        with transaction(self.session):
            if self.suppliers.get(supplier_id) is None:
                raise not_found("supplier")
            if self.products.get(body.product_id) is None:
                raise not_found("product", field="product_id")
            start = body.effective_from or today_ist()
            self._apply_plan(
                supplier_id,
                body.product_id,
                start,
                body.effective_to,
                body.is_primary,
                exclude=None,
            )
            term = self.terms.add(
                SupplierProductTerm(
                    supplier_id=supplier_id,
                    product_id=body.product_id,
                    is_primary=body.is_primary,
                    purchase_price=body.purchase_price,
                    pack_size=body.pack_size,
                    moq_units=body.moq_units,
                    lead_time_days=body.lead_time_days,
                    effective_from=start,
                    effective_to=body.effective_to,
                )
            )
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That date range overlaps an existing term.") from exc
            self._audit(term, before=None, after={n: getattr(term, n) for n in TERM_FIELDS})
            return self._single(term)

    def update(self, term_id: uuid.UUID, body: TermPatch) -> TermOut:
        with transaction(self.session):
            term = self.session.execute(
                self.terms.select_().where(SupplierProductTerm.id == term_id).with_for_update()
            ).scalar_one_or_none()
            if term is None:
                raise not_found("term")
            sent = body.model_fields_set
            before = {n: getattr(term, n) for n in TERM_FIELDS}
            started = term.effective_from <= today_ist()
            if started and any(
                name in sent and getattr(body, name) != getattr(term, name)
                for name in ("purchase_price", "effective_from")
            ):
                raise conflict(
                    "Past prices are history. Add a new term from the date the price changed.",
                )
            values = {n: (getattr(body, n) if n in sent else getattr(term, n)) for n in TERM_FIELDS}
            start, end = values["effective_from"], values["effective_to"]
            if end is not None and end < start:
                raise invalid("effective_to", "cannot be before effective_from")
            if {"effective_from", "effective_to", "is_primary"} & sent:
                self._apply_plan(
                    term.supplier_id,
                    term.product_id,
                    start,
                    end,
                    values["is_primary"],
                    exclude=term.id,
                )
            for name in sent:
                setattr(term, name, getattr(body, name))
            try:
                self.session.flush()
            except IntegrityError as exc:
                raise conflict("That date range overlaps an existing term.") from exc
            old, new = changed_fields(before, {n: getattr(term, n) for n in TERM_FIELDS})
            if new:
                self._audit(term, before=old, after=new)
            return self._single(term)

    def _apply_plan(
        self,
        supplier_id: uuid.UUID,
        product_id: uuid.UUID,
        start: date,
        end: date | None,
        is_primary: bool,
        *,
        exclude: uuid.UUID | None,
    ) -> None:
        """Reject overlaps, or close the earlier open ended term that a new one replaces."""
        stmt = self.terms.select_().where(SupplierProductTerm.product_id == product_id)
        if exclude is not None:
            stmt = stmt.where(SupplierProductTerm.id != exclude)
        others = list(self.session.execute(stmt).scalars())
        by_id: dict[Hashable, SupplierProductTerm] = {t.id: t for t in others}

        same_supplier = [
            Span(t.id, t.effective_from, t.effective_to)
            for t in others
            if t.supplier_id == supplier_id
        ]
        primaries = (
            [
                Span(t.id, t.effective_from, t.effective_to)
                for t in others
                if t.is_primary and t.supplier_id != supplier_id
            ]
            if is_primary
            else []
        )
        closes: dict[Hashable, date] = {}
        for spans, message in (
            (same_supplier, "That date range overlaps an existing term for this product."),
            (primaries, "Another supplier is already the primary one for these dates."),
        ):
            plan = plan_new_span(spans, start, end)
            if not plan.allowed:
                raise conflict(message)
            for key, new_end in plan.close:
                closes[key] = new_end
        for key, new_end in closes.items():
            by_id[key].effective_to = new_end
        if closes:
            self.session.flush()

    def _audit(
        self, term: SupplierProductTerm, *, before: dict[str, Any] | None, after: dict[str, Any]
    ) -> None:
        self.audit.record(
            AuditAction.TERMS_UPDATE,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="supplier_product_term",
            entity_id=term.id,
            before=before,
            after={"supplier_id": term.supplier_id, "product_id": term.product_id, **after},
        )
