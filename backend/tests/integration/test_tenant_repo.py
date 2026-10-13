"""TenantRepo against a real database with two tenants."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.repo import TenantContextError, TenantRepo
from app.models.catalogue import Product
from tests import factories
from tests.conftest import TwoTenants


class ProductRepo(TenantRepo[Product]):
    model = Product


def test_get_returns_own_rows_and_hides_foreign_ones(db: Session, two_tenants: TwoTenants) -> None:
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    assert repo_a.get(two_tenants.a.product.id) is not None
    assert repo_a.get(two_tenants.b.product.id) is None


def test_list_and_count_only_see_the_tenant(db: Session, two_tenants: TwoTenants) -> None:
    extra = factories.make_product(db, two_tenants.a.tenant)
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    repo_b = ProductRepo(db, two_tenants.b.tenant.id)
    assert {p.id for p in repo_a.list_()} == {two_tenants.a.product.id, extra.id}
    assert repo_a.count() == 2
    assert [p.id for p in repo_b.list_()] == [two_tenants.b.product.id]
    assert repo_b.count() == 1


def test_update_statement_cannot_touch_another_tenant(db: Session, two_tenants: TwoTenants) -> None:
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    # Even with the other tenant's id in the WHERE clause, nothing matches.
    result = db.execute(
        repo_a.update_().where(Product.id == two_tenants.b.product.id).values(name="Hijacked")
    )
    assert result.rowcount == 0
    db.refresh(two_tenants.b.product)
    assert two_tenants.b.product.name == "Biscuits 100 g"


def test_delete_statement_cannot_touch_another_tenant(db: Session, two_tenants: TwoTenants) -> None:
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    result = db.execute(repo_a.delete_().where(Product.id == two_tenants.b.product.id))
    assert result.rowcount == 0
    assert ProductRepo(db, two_tenants.b.tenant.id).count() == 1


def test_add_inserts_into_the_repo_tenant(db: Session, two_tenants: TwoTenants) -> None:
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    product = Product(
        sku="NEW-1",
        name="New",
        category_id=two_tenants.a.category.id,
        base_unit="pack",
        tax_rate_id=factories.tax_rate(db).id,
        mrp=10,
        selling_price=9,
    )
    repo_a.add(product)
    db.flush()
    assert product.tenant_id == two_tenants.a.tenant.id
    assert repo_a.count() == 2


def test_add_refuses_an_entity_that_names_another_tenant(
    db: Session, two_tenants: TwoTenants
) -> None:
    repo_a = ProductRepo(db, two_tenants.a.tenant.id)
    with pytest.raises(TenantContextError):
        repo_a.add(two_tenants.b.product)


def test_an_unknown_tenant_sees_nothing(db: Session, two_tenants: TwoTenants) -> None:
    repo = ProductRepo(db, uuid4())
    assert repo.count() == 0
    assert repo.get(two_tenants.a.product.id) is None
