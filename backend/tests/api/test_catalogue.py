"""Categories, products, price history, equivalents and tax rates."""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.models.catalogue import ProductPrice
from app.models.ops import AuditLog
from tests import factories
from tests.conftest import TwoTenants

API = "/api/v1"


def product_payload(db: Session, category_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sku": f"SKU-{factories.short_id()}",
        "name": "Glucose Biscuits 100 g",
        "category_id": str(category_id),
        "base_unit": "pack",
        "tax_rate_id": str(factories.tax_rate(db, "GST5").id),
        "mrp": "10.00",
        "selling_price": "9.50",
    }
    payload.update(overrides)
    return payload


def create_product(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(f"{API}/products", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --------------------------------------------------------------------------- categories


def test_category_create_list_and_edit(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    created = client.post(f"{API}/categories", headers=headers, json={"name": "Dairy & Eggs"})
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "dairy-eggs"
    assert body["parent_id"] is None
    assert body["is_active"] is True

    child = client.post(
        f"{API}/categories", headers=headers, json={"name": "Milk", "parent_id": body["id"]}
    ).json()
    assert child["parent_id"] == body["id"]

    listed = client.get(f"{API}/categories", headers=headers).json()
    assert {c["name"] for c in listed} >= {"Dairy & Eggs", "Milk"}

    edited = client.patch(
        f"{API}/categories/{child['id']}",
        headers=headers,
        json={"name": "Packet milk", "position": 3},
    ).json()
    assert (edited["name"], edited["position"]) == ("Packet milk", 3)


def test_category_slugs_are_unique_per_tenant(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    first = client.post(f"{API}/categories", headers=headers, json={"name": "Snacks"}).json()
    second = client.post(f"{API}/categories", headers=headers, json={"name": "snacks"}).json()
    assert first["slug"] == "snacks"
    assert second["slug"] == "snacks-2"
    # Another tenant can use the same slug.
    other = client.post(f"{API}/categories", headers=two_tenants.b.headers, json={"name": "Snacks"})
    assert other.json()["slug"] == "snacks"


def test_categories_have_two_levels_at_most(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    top = client.post(f"{API}/categories", headers=headers, json={"name": "Top"}).json()
    mid = client.post(
        f"{API}/categories", headers=headers, json={"name": "Mid", "parent_id": top["id"]}
    ).json()
    too_deep = client.post(
        f"{API}/categories", headers=headers, json={"name": "Deep", "parent_id": mid["id"]}
    )
    assert too_deep.status_code == 422
    # A category with children cannot move under another one, and cannot be its own parent.
    other = client.post(f"{API}/categories", headers=headers, json={"name": "Other"}).json()
    moved = client.patch(
        f"{API}/categories/{top['id']}", headers=headers, json={"parent_id": other["id"]}
    )
    assert moved.status_code == 422
    itself = client.patch(
        f"{API}/categories/{other['id']}", headers=headers, json={"parent_id": other["id"]}
    )
    assert itself.status_code == 422
    # A child can move back to the top level with an explicit null.
    lifted = client.patch(
        f"{API}/categories/{mid['id']}", headers=headers, json={"parent_id": None}
    )
    assert lifted.status_code == 200
    assert lifted.json()["parent_id"] is None


def test_category_parent_must_belong_to_the_tenant(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    response = client.post(
        f"{API}/categories",
        headers=two_tenants.a.headers,
        json={"name": "Sneaky", "parent_id": str(two_tenants.b.category.id)},
    )
    assert response.status_code == 404
    assert response.json()["error"]["details"][0]["field"] == "parent_id"


def test_category_list_counts_active_products(client: TestClient, two_tenants: TwoTenants) -> None:
    a = two_tenants.a
    listed = client.get(f"{API}/categories", headers=a.headers).json()
    mine = next(c for c in listed if c["id"] == str(a.category.id))
    assert mine["product_count"] == 1


# --------------------------------------------------------------------------- products: create


def test_create_product_returns_the_detail_and_opens_price_history(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    body = create_product(
        client, a.headers, product_payload(db, a.category.id, barcode="8901234567890")
    )
    assert body["mrp"] == "10.00"
    assert body["selling_price"] == "9.50"
    assert body["tax_rate_code"] == "GST5"
    assert body["tax_rate_pct"] == "5.00"
    assert body["category_name"] == a.category.name
    assert body["on_hand"] == "0.000"
    assert body["is_active"] is True
    assert body["min_stock_qty"] == "0.000"
    history = client.get(f"{API}/products/{body['id']}/prices", headers=a.headers).json()
    assert len(history) == 1
    assert history[0]["effective_from"] == today_ist().isoformat()
    assert history[0]["effective_to"] is None
    audit = db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == a.tenant.id, AuditLog.action == "product.create"
        )
    ).scalar_one()
    assert audit.entity_id == body["id"]


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"selling_price": "10.01"}, "selling_price"),
        ({"mrp": "-1.00", "selling_price": "0.00"}, "mrp"),
        ({"mrp": "10.005"}, "mrp"),
        ({"mrp": 10.5}, "mrp"),
        ({"sku": ""}, "sku"),
        ({"sku": "has space"}, "sku"),
        ({"sku": "x" * 41}, "sku"),
        ({"name": "   "}, "name"),
        ({"base_unit": "crate"}, "base_unit"),
        ({"shelf_life_days": 0}, "shelf_life_days"),
        ({"shelf_life_days": 4000}, "shelf_life_days"),
        ({"min_stock_qty": "-1"}, "min_stock_qty"),
        ({"barcode": "ab"}, "barcode"),
        ({"launched_on": "1990-01-01"}, "launched_on"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_create_product_validation(
    client: TestClient, db: Session, two_tenants: TwoTenants, override: dict[str, Any], field: str
) -> None:
    a = two_tenants.a
    response = client.post(
        f"{API}/products", headers=a.headers, json=product_payload(db, a.category.id, **override)
    )
    assert response.status_code == 422
    fields = [d["field"] for d in response.json()["error"]["details"]]
    assert any(f == field or f.startswith(field) for f in fields), fields


def test_sku_and_barcode_are_unique_per_tenant(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    create_product(
        client, a.headers, product_payload(db, a.category.id, sku="MILK-1", barcode="1111111")
    )
    clash = client.post(
        f"{API}/products",
        headers=a.headers,
        json=product_payload(db, a.category.id, sku="MILK-1"),
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "CONFLICT"
    barcode_clash = client.post(
        f"{API}/products",
        headers=a.headers,
        json=product_payload(db, a.category.id, barcode="1111111"),
    )
    assert barcode_clash.status_code == 409
    # The same SKU and barcode are fine for another tenant.
    create_product(
        client, b.headers, product_payload(db, b.category.id, sku="MILK-1", barcode="1111111")
    )


def test_product_references_must_belong_to_the_tenant(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    foreign_category = client.post(
        f"{API}/products", headers=a.headers, json=product_payload(db, b.category.id)
    )
    assert foreign_category.status_code == 404
    assert foreign_category.json()["error"]["details"][0]["field"] == "category_id"
    missing_rate = client.post(
        f"{API}/products",
        headers=a.headers,
        json=product_payload(db, a.category.id, tax_rate_id=str(uuid.uuid4())),
    )
    assert missing_rate.status_code == 404


def test_medicine_details_are_for_medical_businesses_only(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    fmcg = two_tenants.a
    refused = client.post(
        f"{API}/products",
        headers=fmcg.headers,
        json=product_payload(db, fmcg.category.id, generic_name="Paracetamol", schedule_class="H"),
    )
    assert refused.status_code == 422
    assert {d["field"] for d in refused.json()["error"]["details"]} == {
        "generic_name",
        "schedule_class",
    }

    tenant = factories.make_tenant(db, business_type="medical")
    owner = factories.make_user(db, tenant)
    category = factories.make_category(db, tenant)
    headers = factories.auth_headers(client.app.state.settings, owner)  # type: ignore[attr-defined]
    body = create_product(
        client,
        headers,
        product_payload(
            db,
            category.id,
            base_unit="strip",
            generic_name="Paracetamol",
            strength="500 mg",
            dosage_form="Tablet",
            schedule_class="H",
            is_batch_tracked=True,
            shelf_life_days=730,
        ),
    )
    assert body["generic_name"] == "Paracetamol"
    assert body["schedule_class"] == "H"
    assert body["is_batch_tracked"] is True


# --------------------------------------------------------------------------- products: read


def test_get_product_includes_stock_and_primary_supplier(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    factories.make_balance(db, a.tenant, a.product, on_hand=7)
    factories.make_terms(db, a.tenant, a.supplier, a.product, is_primary=True)
    body = client.get(f"{API}/products/{a.product.id}", headers=a.headers).json()
    assert body["on_hand"] == "7.000"
    assert body["primary_supplier_id"] == str(a.supplier.id)
    assert body["primary_supplier_name"] == a.supplier.name
    assert body["days_of_cover"] is None
    assert body["plan_status"] is None


def test_list_search_filter_sort_and_paging(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    headers = a.headers
    other_category = factories.make_category(db, a.tenant)
    names = [
        ("Parle-G Glucose Biscuits", "PG-100", None, other_category),
        ("Marie Gold Biscuits", "MG-200", "8901000000011", other_category),
        ("Toor Dal 1 kg", "TD-300", None, a.category),
        ("Tata 100% Pure_Salt", "TS-400", None, a.category),
    ]
    for name, sku, barcode, category in names:
        create_product(
            client, headers, product_payload(db, category.id, name=name, sku=sku, barcode=barcode)
        )

    def search(**params: Any) -> dict[str, Any]:
        response = client.get(f"{API}/products", headers=headers, params=params)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    assert {i["sku"] for i in search(q="biscuit")["items"]} == {"PG-100", "MG-200", a.product.sku}
    assert [i["sku"] for i in search(q="td-300")["items"]] == ["TD-300"]
    assert [i["sku"] for i in search(q="8901000000011")["items"]] == ["MG-200"]
    # SKU match ranks before a name match.
    ranked = search(q="mg-200")["items"]
    assert ranked[0]["sku"] == "MG-200"
    # LIKE wildcards in the search term are literal.
    assert [i["sku"] for i in search(q="100%")["items"]] == ["TS-400"]
    assert search(q="%")["total"] == 1
    assert search(q="_")["total"] == 1
    assert search(q="no such product")["total"] == 0

    assert search(category_id=str(other_category.id))["total"] == 2
    assert search(sort="name:desc")["items"][0]["name"] == "Toor Dal 1 kg"
    page = search(page=2, page_size=2, sort="sku:asc")
    assert (page["page"], page["page_size"], page["total"]) == (2, 2, 5)
    assert len(page["items"]) == 2


def test_list_filters_by_status_batch_tracking_and_supplier(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    headers = a.headers
    tracked = create_product(
        client, headers, product_payload(db, a.category.id, is_batch_tracked=True, sku="TRK-1")
    )
    client.post(f"{API}/products/{a.product.id}/deactivate", headers=headers)
    factories.make_terms(db, a.tenant, a.supplier, db.get(type(a.product), tracked["id"]))

    def skus(**params: Any) -> set[str]:
        body = client.get(f"{API}/products", headers=headers, params=params).json()
        return {item["sku"] for item in body["items"]}

    assert skus() == {"TRK-1"}  # active only by default
    assert skus(status="inactive") == {a.product.sku}
    assert skus(status="all") == {"TRK-1", a.product.sku}
    assert skus(batch_tracked="true", status="all") == {"TRK-1"}
    assert skus(batch_tracked="false", status="all") == {a.product.sku}
    assert skus(supplier_id=str(a.supplier.id)) == {"TRK-1"}


@pytest.mark.parametrize("sort", ["bogus:asc", "name:sideways", "name; drop table products"])
def test_unknown_sort_fields_are_a_422(
    client: TestClient, two_tenants: TwoTenants, sort: str
) -> None:
    response = client.get(f"{API}/products", headers=two_tenants.a.headers, params={"sort": sort})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "sort"


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 201}, {"page_size": 0}, {"status": "gone"}]
)
def test_bad_paging_or_filter_values_are_a_422(
    client: TestClient, two_tenants: TwoTenants, params: dict[str, Any]
) -> None:
    assert (
        client.get(f"{API}/products", headers=two_tenants.a.headers, params=params).status_code
        == 422
    )


# --------------------------------------------------------------------------- products: update


def test_price_change_closes_the_old_row_and_opens_a_new_one(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = create_product(client, a.headers, product_payload(db, a.category.id))
    # Make the opening price row older, so the change below is a new day.
    first = db.execute(
        select(ProductPrice).where(ProductPrice.product_id == uuid.UUID(product["id"]))
    ).scalar_one()
    first.effective_from = today_ist() - timedelta(days=10)
    db.flush()

    changed = client.patch(
        f"{API}/products/{product['id']}",
        headers=a.headers,
        json={"mrp": "12.00", "selling_price": "11.00", "price_change_reason": "Supplier increase"},
    )
    assert changed.status_code == 200
    assert changed.json()["mrp"] == "12.00"
    history = client.get(f"{API}/products/{product['id']}/prices", headers=a.headers).json()
    assert [
        (h["selling_price"], h["effective_from"], h["effective_to"], h["reason"]) for h in history
    ] == [
        ("11.00", today_ist().isoformat(), None, "Supplier increase"),
        (
            "9.50",
            (today_ist() - timedelta(days=10)).isoformat(),
            (today_ist() - timedelta(days=1)).isoformat(),
            "Opening price",
        ),
    ]
    audit = db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == a.tenant.id, AuditLog.action == "product.price_change"
        )
    ).scalar_one()
    assert audit.before == {"mrp": "10.00", "selling_price": "9.50"}
    assert audit.after == {"mrp": "12.00", "selling_price": "11.00"}


def test_second_price_change_on_the_same_day_edits_that_row(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = create_product(client, a.headers, product_payload(db, a.category.id))
    client.patch(
        f"{API}/products/{product['id']}", headers=a.headers, json={"selling_price": "9.00"}
    )
    client.patch(
        f"{API}/products/{product['id']}", headers=a.headers, json={"selling_price": "8.50"}
    )
    history = client.get(f"{API}/products/{product['id']}/prices", headers=a.headers).json()
    assert len(history) == 1
    assert history[0]["selling_price"] == "8.50"


def test_patch_validates_the_merged_state_and_unique_fields(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = create_product(client, a.headers, product_payload(db, a.category.id, sku="ONE"))
    create_product(client, a.headers, product_payload(db, a.category.id, sku="TWO"))
    url = f"{API}/products/{product['id']}"
    assert (
        client.patch(url, headers=a.headers, json={"mrp": "9.00"}).status_code == 422
    )  # below price
    assert client.patch(url, headers=a.headers, json={"sku": "TWO"}).status_code == 409
    assert client.patch(url, headers=a.headers, json={"sku": "ONE"}).status_code == 200  # own sku
    assert client.patch(url, headers=a.headers, json={"name": None}).status_code == 422
    assert (
        client.patch(url, headers=a.headers, json={"category_id": str(uuid.uuid4())}).status_code
        == 404
    )
    assert (
        client.patch(url, headers=a.headers, json={"generic_name": "Paracetamol"}).status_code
        == 422
    )
    cleared = client.patch(url, headers=a.headers, json={"brand": "Parle"}).json()
    assert cleared["brand"] == "Parle"
    assert client.patch(url, headers=a.headers, json={"brand": None}).json()["brand"] is None


def test_batch_tracking_cannot_change_once_stock_history_exists(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/products/{a.product.id}"
    assert client.patch(url, headers=a.headers, json={"is_batch_tracked": True}).status_code == 200
    factories.make_movement(db, a.tenant, a.product)
    refused = client.patch(url, headers=a.headers, json={"is_batch_tracked": False})
    assert refused.status_code == 409
    assert client.patch(url, headers=a.headers, json={"is_batch_tracked": True}).status_code == 200


def test_deactivate_and_activate_are_audited(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    off = client.post(f"{API}/products/{a.product.id}/deactivate", headers=a.headers).json()
    assert off["is_active"] is False
    on = client.post(f"{API}/products/{a.product.id}/activate", headers=a.headers).json()
    assert on["is_active"] is True
    client.post(f"{API}/products/{a.product.id}/activate", headers=a.headers)  # already active
    actions = (
        db.execute(
            select(AuditLog.action).where(AuditLog.tenant_id == a.tenant.id).order_by(AuditLog.id)
        )
        .scalars()
        .all()
    )
    assert actions == ["product.deactivate", "product.activate"]


# --------------------------------------------------------------------------- equivalents


def test_equivalents_are_linked_listed_and_removed(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    other = factories.make_product(db, a.tenant, name="Dolo 650", category=a.category)
    factories.make_balance(db, a.tenant, other, on_hand=12)
    url = f"{API}/products/{a.product.id}/equivalents"
    created = client.post(
        url,
        headers=a.headers,
        json={"equivalent_product_id": str(other.id), "note": "Customer asked for this"},
    )
    assert created.status_code == 201
    link = created.json()
    assert link["equivalent_name"] == "Dolo 650"
    assert link["equivalent_on_hand"] == "12.000"
    assert client.get(url, headers=a.headers).json()[0]["id"] == link["id"]
    dup = client.post(url, headers=a.headers, json={"equivalent_product_id": str(other.id)})
    assert dup.status_code == 409
    assert client.delete(f"{url}/{link['id']}", headers=a.headers).status_code == 204
    assert client.get(url, headers=a.headers).json() == []
    assert client.delete(f"{url}/{link['id']}", headers=a.headers).status_code == 404


def test_equivalent_rules(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a, two_tenants.b
    url = f"{API}/products/{a.product.id}/equivalents"
    itself = client.post(url, headers=a.headers, json={"equivalent_product_id": str(a.product.id)})
    assert itself.status_code == 422
    foreign = client.post(url, headers=a.headers, json={"equivalent_product_id": str(b.product.id)})
    assert foreign.status_code == 404
    assert foreign.json()["error"]["details"][0]["field"] == "equivalent_product_id"


# --------------------------------------------------------------------------- tax rates


def test_tax_rates_list_the_slabs_in_force(client: TestClient, two_tenants: TwoTenants) -> None:
    body = client.get(f"{API}/tax-rates", headers=two_tenants.a.headers).json()
    assert [r["code"] for r in body] == ["GST0", "GST5", "GST18", "GST40"]
    assert body[1]["rate_pct"] == "5.00"
    assert all(date.fromisoformat(r["effective_from"]) <= today_ist() for r in body)


# --------------------------------------------------------------------------- 401 and isolation


def routes(a: Any, b: Any) -> list[tuple[str, str, dict[str, Any] | None]]:
    """(method, path, body) for every catalogue route, aimed at tenant A's rows."""
    link_id = uuid.uuid4()
    return [
        ("PATCH", f"/categories/{a.category.id}", {"name": "Hacked"}),
        ("GET", f"/products/{a.product.id}", None),
        ("PATCH", f"/products/{a.product.id}", {"name": "Hacked"}),
        ("POST", f"/products/{a.product.id}/deactivate", None),
        ("POST", f"/products/{a.product.id}/activate", None),
        ("GET", f"/products/{a.product.id}/prices", None),
        ("GET", f"/products/{a.product.id}/equivalents", None),
        (
            "POST",
            f"/products/{a.product.id}/equivalents",
            {"equivalent_product_id": str(b.product.id)},
        ),
        ("DELETE", f"/products/{a.product.id}/equivalents/{link_id}", None),
    ]


ALL_ROUTES = [
    ("GET", "/categories", None),
    ("POST", "/categories", {"name": "X"}),
    ("PATCH", f"/categories/{uuid.uuid4()}", {"name": "X"}),
    ("GET", "/products", None),
    ("POST", "/products", {}),
    ("GET", f"/products/{uuid.uuid4()}", None),
    ("PATCH", f"/products/{uuid.uuid4()}", {}),
    ("POST", f"/products/{uuid.uuid4()}/deactivate", None),
    ("POST", f"/products/{uuid.uuid4()}/activate", None),
    ("GET", f"/products/{uuid.uuid4()}/prices", None),
    ("GET", f"/products/{uuid.uuid4()}/equivalents", None),
    ("POST", f"/products/{uuid.uuid4()}/equivalents", {}),
    ("DELETE", f"/products/{uuid.uuid4()}/equivalents/{uuid.uuid4()}", None),
    ("GET", "/tax-rates", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ALL_ROUTES)
def test_every_catalogue_route_needs_a_token(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"{API}{path}", json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_tenant_b_cannot_see_or_change_tenant_a_rows(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    linked = factories.make_product(db, a.tenant, category=a.category)
    link = client.post(
        f"{API}/products/{a.product.id}/equivalents",
        headers=a.headers,
        json={"equivalent_product_id": str(linked.id)},
    ).json()

    for method, path, body in routes(a, b):
        response = client.request(method, f"{API}{path}", headers=b.headers, json=body)
        assert response.status_code == 404, (method, path, response.status_code, response.text)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    deleted = client.delete(
        f"{API}/products/{a.product.id}/equivalents/{link['id']}", headers=b.headers
    )
    assert deleted.status_code == 404

    # Nothing changed for tenant A.
    product = client.get(f"{API}/products/{a.product.id}", headers=a.headers).json()
    assert product["name"] != "Hacked"
    assert product["is_active"] is True
    assert (
        len(client.get(f"{API}/products/{a.product.id}/equivalents", headers=a.headers).json()) == 1
    )

    # Lists never leak across tenants.
    mine = client.get(f"{API}/products", headers=b.headers, params={"status": "all"}).json()
    assert {item["id"] for item in mine["items"]} == {str(b.product.id)}
    categories = client.get(f"{API}/categories", headers=b.headers).json()
    assert {c["id"] for c in categories} == {str(b.category.id)}


def test_a_tenant_id_in_the_body_is_ignored(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    payload = product_payload(db, a.category.id, tenant_id=str(b.tenant.id))
    response = client.post(f"{API}/products", headers=a.headers, json=payload)
    assert response.status_code == 422  # unknown fields are refused, never trusted
