"""A row can never point at another tenant's data, even by a hand written INSERT."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.tenancy import RefreshToken
from tests import factories
from tests.conftest import TwoTenants, rejected

Case = Callable[[Session, TwoTenants], Any]


def _product_with_foreign_category(db: Session, t: TwoTenants) -> Any:
    return factories.make_product(db, t.b.tenant, category=t.a.category)


def _category_with_foreign_parent(db: Session, t: TwoTenants) -> Any:
    return factories.make_category(db, t.b.tenant, parent_id=t.a.category.id)


def _term_with_foreign_supplier(db: Session, t: TwoTenants) -> Any:
    return factories.make_terms(db, t.b.tenant, t.a.supplier, t.b.product)


def _term_with_foreign_product(db: Session, t: TwoTenants) -> Any:
    return factories.make_terms(db, t.b.tenant, t.b.supplier, t.a.product)


def _batch_with_foreign_product(db: Session, t: TwoTenants) -> Any:
    return factories.make_batch(db, t.b.tenant, t.a.product)


def _sale_line_with_foreign_sale(db: Session, t: TwoTenants) -> Any:
    sale = factories.make_sale(db, t.a.tenant)
    return factories.make_sale_line(db, t.b.tenant, sale, t.b.product)


def _sale_line_with_foreign_product(db: Session, t: TwoTenants) -> Any:
    sale = factories.make_sale(db, t.b.tenant)
    return factories.make_sale_line(db, t.b.tenant, sale, t.a.product)


def _sale_line_with_foreign_batch(db: Session, t: TwoTenants) -> Any:
    batch = factories.make_batch(db, t.a.tenant, t.a.product)
    sale = factories.make_sale(db, t.b.tenant)
    return factories.make_sale_line(db, t.b.tenant, sale, t.b.product, batch_id=batch.id)


def _po_with_foreign_supplier(db: Session, t: TwoTenants) -> Any:
    return factories.make_po(db, t.b.tenant, t.a.supplier)


def _po_line_with_foreign_po(db: Session, t: TwoTenants) -> Any:
    po = factories.make_po(db, t.a.tenant, t.a.supplier)
    return factories.make_po_line(db, t.b.tenant, po, t.b.product)


def _balance_with_foreign_product(db: Session, t: TwoTenants) -> Any:
    return factories.make_balance(db, t.b.tenant, t.a.product)


def _movement_with_foreign_batch(db: Session, t: TwoTenants) -> Any:
    batch = factories.make_batch(db, t.a.tenant, t.a.product)
    return factories.make_movement(db, t.b.tenant, t.b.product, batch_id=batch.id)


def _recommendation_line_with_foreign_run(db: Session, t: TwoTenants) -> Any:
    run = factories.make_recommendation_run(db, t.a.tenant)
    return factories.make_recommendation_line(db, t.b.tenant, run, t.b.product)


def _recommendation_line_with_foreign_supplier(db: Session, t: TwoTenants) -> Any:
    run = factories.make_recommendation_run(db, t.b.tenant)
    return factories.make_recommendation_line(
        db, t.b.tenant, run, t.b.product, supplier_id=t.a.supplier.id
    )


def _refresh_token_with_foreign_user(db: Session, t: TwoTenants) -> Any:
    token = RefreshToken(
        tenant_id=t.b.tenant.id,
        user_id=t.a.user.id,
        family_id=uuid4(),
        token_hash="0" * 64,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    db.add(token)
    db.flush()
    return token


CASES: dict[str, Case] = {
    "products.category_id": _product_with_foreign_category,
    "categories.parent_id": _category_with_foreign_parent,
    "supplier_product_terms.supplier_id": _term_with_foreign_supplier,
    "supplier_product_terms.product_id": _term_with_foreign_product,
    "product_batches.product_id": _batch_with_foreign_product,
    "sale_lines.sale_id": _sale_line_with_foreign_sale,
    "sale_lines.product_id": _sale_line_with_foreign_product,
    "sale_lines.batch_id": _sale_line_with_foreign_batch,
    "purchase_orders.supplier_id": _po_with_foreign_supplier,
    "purchase_order_lines.po_id": _po_line_with_foreign_po,
    "stock_balances.product_id": _balance_with_foreign_product,
    "inventory_movements.batch_id": _movement_with_foreign_batch,
    "recommendation_lines.run_id": _recommendation_line_with_foreign_run,
    "recommendation_lines.supplier_id": _recommendation_line_with_foreign_supplier,
    "refresh_tokens.user_id": _refresh_token_with_foreign_user,
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_cross_tenant_reference_is_rejected(
    db: Session, two_tenants: TwoTenants, case: Case
) -> None:
    with rejected(db, match="foreign key constraint"):
        case(db, two_tenants)


def test_the_same_references_inside_one_tenant_are_accepted(db: Session) -> None:
    """Control: the rule must not block legitimate rows."""
    tenant = factories.make_tenant(db)
    category = factories.make_category(db, tenant)
    child = factories.make_category(db, tenant, parent_id=category.id)
    product = factories.make_product(db, tenant, category=child)
    supplier = factories.make_supplier(db, tenant)
    factories.make_terms(db, tenant, supplier, product)
    batch = factories.make_batch(db, tenant, product)
    sale = factories.make_sale(db, tenant)
    factories.make_sale_line(db, tenant, sale, product, batch_id=batch.id)
    po = factories.make_po(db, tenant, supplier)
    factories.make_po_line(db, tenant, po, product)
    factories.make_balance(db, tenant, product, batch)
    factories.make_movement(db, tenant, product, batch_id=batch.id)
    run = factories.make_recommendation_run(db, tenant)
    factories.make_recommendation_line(db, tenant, run, product, supplier_id=supplier.id)


def test_a_missing_supplier_on_a_recommendation_line_is_allowed(
    db: Session, two_tenants: TwoTenants
) -> None:
    """Nullable composite keys are skipped when the nullable column is NULL."""
    run = factories.make_recommendation_run(db, two_tenants.a.tenant)
    line = factories.make_recommendation_line(
        db, two_tenants.a.tenant, run, two_tenants.a.product, supplier_id=None
    )
    assert line.supplier_id is None
