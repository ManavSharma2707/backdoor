"""TenantRepo behaviour that needs no database."""

import uuid

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.repo import TenantContextError, TenantRepo
from app.models.catalogue import Product
from app.models.reference import TaxRate


class ProductRepo(TenantRepo[Product]):
    model = Product


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


def sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_repo_cannot_be_built_without_a_tenant() -> None:
    with pytest.raises(TenantContextError):
        ProductRepo(Session(), None)


def test_repo_refuses_a_tenant_id_that_is_not_a_uuid() -> None:
    with pytest.raises(TenantContextError):
        ProductRepo(Session(), "11111111-1111-1111-1111-111111111111")  # type: ignore[arg-type]


def test_repo_refuses_models_without_tenant_id() -> None:
    class TaxRateRepo(TenantRepo[TaxRate]):
        model = TaxRate

    with pytest.raises(TypeError, match="not a tenant owned model"):
        TaxRateRepo(Session(), TENANT)


@pytest.mark.parametrize("builder", ["select_", "update_", "delete_"])
def test_every_statement_is_filtered_by_tenant(builder: str) -> None:
    repo = ProductRepo(Session(), TENANT)
    statement = getattr(repo, builder)()
    text = sql(statement)
    assert "products.tenant_id = %(tenant_id_1)s" in text
    assert statement.compile().params["tenant_id_1"] == TENANT


def test_get_adds_the_id_filter_on_top_of_the_tenant_filter() -> None:
    repo = ProductRepo(Session(), TENANT)
    statement = repo.select_().where(Product.id == uuid.uuid4())
    text = sql(statement)
    assert "tenant_id" in text
    assert text.count("WHERE") == 1


def test_add_stamps_the_tenant_on_the_entity() -> None:
    session = Session()
    repo = ProductRepo(session, TENANT)
    product = Product(sku="A", name="A")
    repo.add(product)
    assert product.tenant_id == TENANT


def test_add_refuses_an_entity_of_another_tenant() -> None:
    repo = ProductRepo(Session(), TENANT)
    foreign = Product(sku="A", name="A", tenant_id=uuid.uuid4())
    with pytest.raises(TenantContextError, match="different tenant"):
        repo.add(foreign)
