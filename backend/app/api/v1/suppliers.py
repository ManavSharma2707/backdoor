"""Suppliers and effective dated terms (`api-spec.md` section 4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import OwnerCtx, SessionDep, owner_context
from app.core.pagination import Page, PageDep
from app.schemas.suppliers import (
    SupplierCreate,
    SupplierOut,
    SupplierPatch,
    TermCreate,
    TermOut,
    TermPatch,
)
from app.services.supplier_service import SupplierService, TermService

guard = [Depends(owner_context)]
suppliers = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=guard)
terms = APIRouter(prefix="/supplier-terms", tags=["suppliers"], dependencies=guard)


@suppliers.get("", response_model=Page[SupplierOut], summary="List suppliers")
def list_suppliers(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=80, description="Name or code")] = None,
    active: bool | None = None,
    sort: Annotated[str | None, Query(description="name, code, created_at")] = None,
) -> Page[SupplierOut]:
    items, total = SupplierService(session, ctx).search(page=page, q=q, active=active, sort=sort)
    return Page[SupplierOut](items=items, total=total, page=page.page, page_size=page.page_size)


@suppliers.post("", response_model=SupplierOut, status_code=201, summary="Add a supplier")
def create_supplier(body: SupplierCreate, ctx: OwnerCtx, session: SessionDep) -> SupplierOut:
    return SupplierService(session, ctx).create(body)


@suppliers.get("/{supplier_id}", response_model=SupplierOut, summary="Supplier detail")
def get_supplier(supplier_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> SupplierOut:
    return SupplierService(session, ctx).get(supplier_id)


@suppliers.patch("/{supplier_id}", response_model=SupplierOut, summary="Edit a supplier")
def update_supplier(
    supplier_id: uuid.UUID, body: SupplierPatch, ctx: OwnerCtx, session: SessionDep
) -> SupplierOut:
    return SupplierService(session, ctx).update(supplier_id, body)


@suppliers.get(
    "/{supplier_id}/terms", response_model=list[TermOut], summary="Prices and terms by product"
)
def list_terms(
    supplier_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    current: Annotated[bool, Query(description="Only terms in force today")] = False,
) -> list[TermOut]:
    return TermService(session, ctx).list_terms(supplier_id, current_only=current)


@suppliers.post(
    "/{supplier_id}/terms",
    response_model=TermOut,
    status_code=201,
    summary="Add a price and terms for a product",
)
def create_term(
    supplier_id: uuid.UUID, body: TermCreate, ctx: OwnerCtx, session: SessionDep
) -> TermOut:
    """A new open ended term closes the earlier open ended one the day before it starts.
    Overlapping dates are refused. A new primary term replaces the current primary one."""
    return TermService(session, ctx).create(supplier_id, body)


@terms.patch("/{term_id}", response_model=TermOut, summary="Correct or end a term")
def update_term(term_id: uuid.UUID, body: TermPatch, ctx: OwnerCtx, session: SessionDep) -> TermOut:
    return TermService(session, ctx).update(term_id, body)
