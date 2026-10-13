"""Categories, products, price history, equivalents and tax rates (`api-spec.md` section 4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.deps import OwnerCtx, SessionDep, owner_context
from app.core.pagination import Page, PageDep
from app.schemas.catalogue import (
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    EquivalentCreate,
    EquivalentOut,
    PriceHistoryOut,
    ProductCreate,
    ProductOut,
    ProductPatch,
    ProductStatus,
    TaxRateOut,
)
from app.services.catalogue_service import (
    CategoryService,
    EquivalentService,
    ProductService,
    list_tax_rates,
)

guard = [Depends(owner_context)]
categories = APIRouter(prefix="/categories", tags=["catalogue"], dependencies=guard)
products = APIRouter(prefix="/products", tags=["catalogue"], dependencies=guard)
tax_rates = APIRouter(prefix="/tax-rates", tags=["catalogue"], dependencies=guard)


@categories.get("", response_model=list[CategoryOut], summary="List categories")
def list_categories(ctx: OwnerCtx, session: SessionDep) -> list[CategoryOut]:
    """Flat list ordered by position. `parent_id` builds the two level tree."""
    return CategoryService(session, ctx).list_all()


@categories.post("", response_model=CategoryOut, status_code=201, summary="Add a category")
def create_category(body: CategoryCreate, ctx: OwnerCtx, session: SessionDep) -> CategoryOut:
    return CategoryService(session, ctx).create(body)


@categories.patch("/{category_id}", response_model=CategoryOut, summary="Edit a category")
def update_category(
    category_id: uuid.UUID, body: CategoryPatch, ctx: OwnerCtx, session: SessionDep
) -> CategoryOut:
    return CategoryService(session, ctx).update(category_id, body)


@products.get("", response_model=Page[ProductOut], summary="Search and list products")
def list_products(
    ctx: OwnerCtx,
    session: SessionDep,
    page: PageDep,
    q: Annotated[
        str | None, Query(max_length=80, description="Name, SKU, brand, generic name or barcode")
    ] = None,
    category_id: uuid.UUID | None = None,
    status: ProductStatus = "active",
    supplier_id: uuid.UUID | None = None,
    batch_tracked: bool | None = None,
    sort: Annotated[
        str | None, Query(description="name, sku, selling_price, created_at, on_hand")
    ] = None,
) -> Page[ProductOut]:
    items, total = ProductService(session, ctx).search(
        page=page,
        q=q,
        category_id=category_id,
        status=status,
        supplier_id=supplier_id,
        batch_tracked=batch_tracked,
        sort=sort,
    )
    return Page[ProductOut](items=items, total=total, page=page.page, page_size=page.page_size)


@products.post("", response_model=ProductOut, status_code=201, summary="Add a product")
def create_product(body: ProductCreate, ctx: OwnerCtx, session: SessionDep) -> ProductOut:
    return ProductService(session, ctx).create(body)


@products.get("/{product_id}", response_model=ProductOut, summary="Product detail")
def get_product(product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ProductOut:
    return ProductService(session, ctx).get(product_id)


@products.patch("/{product_id}", response_model=ProductOut, summary="Edit a product")
def update_product(
    product_id: uuid.UUID, body: ProductPatch, ctx: OwnerCtx, session: SessionDep
) -> ProductOut:
    """A new MRP or selling price closes the old price row and opens a new one."""
    return ProductService(session, ctx).update(product_id, body)


@products.post("/{product_id}/deactivate", response_model=ProductOut, summary="Stop selling")
def deactivate_product(product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ProductOut:
    return ProductService(session, ctx).set_active(product_id, active=False)


@products.post("/{product_id}/activate", response_model=ProductOut, summary="Start selling again")
def activate_product(product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ProductOut:
    return ProductService(session, ctx).set_active(product_id, active=True)


@products.get("/{product_id}/prices", response_model=list[PriceHistoryOut], summary="Price history")
def product_prices(
    product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep
) -> list[PriceHistoryOut]:
    rows = ProductService(session, ctx).price_history(product_id)
    return [PriceHistoryOut.model_validate(row) for row in rows]


@products.get(
    "/{product_id}/equivalents", response_model=list[EquivalentOut], summary="Your equivalents"
)
def list_equivalents(
    product_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep
) -> list[EquivalentOut]:
    """Links you defined yourself. The system never suggests substitutes."""
    return EquivalentService(session, ctx).list_links(product_id)


@products.post(
    "/{product_id}/equivalents",
    response_model=EquivalentOut,
    status_code=201,
    summary="Link an equivalent",
)
def create_equivalent(
    product_id: uuid.UUID, body: EquivalentCreate, ctx: OwnerCtx, session: SessionDep
) -> EquivalentOut:
    return EquivalentService(session, ctx).create(product_id, body)


@products.delete(
    "/{product_id}/equivalents/{link_id}", status_code=204, summary="Remove an equivalent link"
)
def delete_equivalent(
    product_id: uuid.UUID, link_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep
) -> Response:
    EquivalentService(session, ctx).delete(product_id, link_id)
    return Response(status_code=204)


@tax_rates.get("", response_model=list[TaxRateOut], summary="GST rates in force")
def get_tax_rates(session: SessionDep) -> list[TaxRateOut]:
    """Reference list, informational only. Backroom is not a tax filing tool."""
    return list_tax_rates(session)
