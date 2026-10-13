"""Suppliers and effective dated terms."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.models.ops import AuditLog
from app.models.suppliers import SupplierProductTerm
from app.models.tenancy import BusinessSettings
from tests import factories
from tests.conftest import TwoTenants

API = "/api/v1"


def supplier_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": f"S{factories.short_id()}", "name": "Metro Wholesale"}
    payload.update(overrides)
    return payload


def term_payload(product_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"product_id": str(product_id), "purchase_price": "8.5000"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- suppliers


def test_create_get_and_list_supplier(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    created = client.post(
        f"{API}/suppliers",
        headers=headers,
        json=supplier_payload(
            code="METRO-1",
            email="orders@metro.example.com",
            phone="+91 98765 43210",
            payment_terms_days=15,
            default_lead_time_days=2,
            delivery_weekdays=[5, 2, 2],
            min_order_value="5000.00",
            accepts_expiry_returns=True,
            expiry_return_window_days=60,
        ),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["delivery_weekdays"] == [2, 5]
    assert body["min_order_value"] == "5000.00"
    assert body["credit_limit"] is None
    assert body["current_terms"] == 0
    assert client.get(f"{API}/suppliers/{body['id']}", headers=headers).json() == body
    listed = client.get(f"{API}/suppliers", headers=headers, params={"q": "metro"}).json()
    assert [s["code"] for s in listed["items"]] == ["METRO-1"]


@pytest.mark.parametrize(
    "override",
    [
        {"code": "has space"},
        {"name": " "},
        {"email": "not-an-email"},
        {"phone": "call me"},
        {"payment_terms_days": 400},
        {"default_lead_time_days": 61},
        {"delivery_weekdays": [0]},
        {"delivery_weekdays": [8]},
        {"min_order_value": "-5.00"},
        {"min_order_value": 100.5},
        {"unknown": 1},
    ],
)
def test_supplier_validation(
    client: TestClient, two_tenants: TwoTenants, override: dict[str, Any]
) -> None:
    response = client.post(
        f"{API}/suppliers", headers=two_tenants.a.headers, json=supplier_payload(**override)
    )
    assert response.status_code == 422


def test_supplier_codes_are_unique_per_tenant(client: TestClient, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a.headers, two_tenants.b.headers
    assert (
        client.post(f"{API}/suppliers", headers=a, json=supplier_payload(code="X1")).status_code
        == 201
    )
    clash = client.post(f"{API}/suppliers", headers=a, json=supplier_payload(code="X1"))
    assert clash.status_code == 409
    assert clash.json()["error"]["details"][0]["field"] == "code"
    assert (
        client.post(f"{API}/suppliers", headers=b, json=supplier_payload(code="X1")).status_code
        == 201
    )


def test_patch_supplier_changes_only_what_is_sent_and_audits(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}"
    body = client.patch(
        url, headers=a.headers, json={"default_lead_time_days": 4, "is_active": False}
    ).json()
    assert body["default_lead_time_days"] == 4
    assert body["is_active"] is False
    assert body["name"] == a.supplier.name
    assert client.patch(url, headers=a.headers, json={"name": None}).status_code == 422
    audit = db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == a.tenant.id, AuditLog.action == "supplier.update"
        )
    ).scalar_one()
    assert audit.after == {"default_lead_time_days": 4, "is_active": False}
    assert audit.before == {"default_lead_time_days": None, "is_active": True}
    only_active = client.get(
        f"{API}/suppliers", headers=a.headers, params={"active": "true"}
    ).json()
    assert only_active["total"] == 0


# --------------------------------------------------------------------------- terms


def test_term_defaults_and_listing(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    created = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers, json=term_payload(a.product.id)
    )
    assert created.status_code == 201
    term = created.json()
    assert term["purchase_price"] == "8.5000"
    assert term["pack_size"] == "1.000"
    assert term["moq_units"] == "0.000"
    assert term["effective_from"] == today_ist().isoformat()
    assert term["effective_to"] is None
    assert term["in_force"] is True
    assert term["is_primary"] is False
    assert term["product_sku"] == a.product.sku
    listed = client.get(f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers).json()
    assert [t["id"] for t in listed] == [term["id"]]
    supplier = client.get(f"{API}/suppliers/{a.supplier.id}", headers=a.headers).json()
    assert supplier["current_terms"] == 1


def test_lead_time_resolution_shows_up_on_the_term(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}/terms"
    # No term, supplier or business value: the business default (3 days) is assumed.
    first = client.post(url, headers=a.headers, json=term_payload(a.product.id)).json()
    assert (first["resolved_lead_time_days"], first["lead_time_source"]) == (3, "business_default")

    db.add(BusinessSettings(tenant_id=a.tenant.id, default_lead_time_days=5))
    db.flush()
    assert client.get(url, headers=a.headers).json()[0]["resolved_lead_time_days"] == 5

    client.patch(
        f"{API}/suppliers/{a.supplier.id}", headers=a.headers, json={"default_lead_time_days": 2}
    )
    after_supplier = client.get(url, headers=a.headers).json()[0]
    assert (after_supplier["resolved_lead_time_days"], after_supplier["lead_time_source"]) == (
        2,
        "supplier_default",
    )

    patched = client.patch(
        f"{API}/supplier-terms/{first['id']}", headers=a.headers, json={"lead_time_days": 0}
    ).json()
    assert (patched["resolved_lead_time_days"], patched["lead_time_source"]) == (0, "product_term")


def test_a_new_open_ended_term_ends_the_previous_one_the_day_before(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}/terms"
    start_old = today_ist() - timedelta(days=60)
    start_new = today_ist() - timedelta(days=10)
    old = client.post(
        url,
        headers=a.headers,
        json=term_payload(a.product.id, effective_from=start_old.isoformat()),
    ).json()
    new = client.post(
        url,
        headers=a.headers,
        json=term_payload(
            a.product.id, purchase_price="9.0000", effective_from=start_new.isoformat()
        ),
    ).json()
    terms = {t["id"]: t for t in client.get(url, headers=a.headers).json()}
    assert terms[old["id"]]["effective_to"] == (start_new - timedelta(days=1)).isoformat()
    assert terms[old["id"]]["in_force"] is False
    assert terms[new["id"]]["effective_to"] is None
    assert terms[new["id"]]["in_force"] is True
    current = client.get(url, headers=a.headers, params={"current": "true"}).json()
    assert [t["id"] for t in current] == [new["id"]]
    audit_rows = (
        db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == a.tenant.id, AuditLog.action == "terms.update"
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 2


@pytest.mark.parametrize(
    ("start", "end"),
    [(-20, None), (-15, -5), (-35, -25), (-10, None), (-30, -30), (-40, None), (-40, -30)],
)
def test_overlapping_dates_are_refused(
    client: TestClient, two_tenants: TwoTenants, start: int, end: int | None
) -> None:
    """The existing term runs from 30 days ago to 10 days ago, both days included."""
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}/terms"
    base = today_ist()
    first = client.post(
        url,
        headers=a.headers,
        json=term_payload(
            a.product.id,
            effective_from=(base - timedelta(days=30)).isoformat(),
            effective_to=(base - timedelta(days=10)).isoformat(),
        ),
    )
    assert first.status_code == 201
    payload = term_payload(a.product.id, effective_from=(base + timedelta(days=start)).isoformat())
    if end is not None:
        payload["effective_to"] = (base + timedelta(days=end)).isoformat()
    response = client.post(url, headers=a.headers, json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_terms_that_do_not_overlap_are_accepted(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}/terms"
    base = today_ist()
    for start, end in ((-60, -41), (-40, -21), (-20, None)):
        payload = term_payload(
            a.product.id, effective_from=(base + timedelta(days=start)).isoformat()
        )
        if end is not None:
            payload["effective_to"] = (base + timedelta(days=end)).isoformat()
        assert client.post(url, headers=a.headers, json=payload).status_code == 201


def test_end_before_start_is_a_validation_error(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    response = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(a.product.id, effective_from="2026-10-10", effective_to="2026-10-01"),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "override",
    [
        {"purchase_price": "0"},
        {"purchase_price": "-1"},
        {"pack_size": "0"},
        {"moq_units": "-1"},
        {"lead_time_days": -1},
        {"lead_time_days": 99},
        {"purchase_price": 8.5},
    ],
)
def test_term_validation(
    client: TestClient, two_tenants: TwoTenants, override: dict[str, Any]
) -> None:
    a = two_tenants.a
    response = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(a.product.id, **override),
    )
    assert response.status_code == 422


def test_only_one_primary_supplier_per_product_at_a_time(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    other_supplier = factories.make_supplier(db, a.tenant)
    base = today_ist()
    first = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(
            a.product.id, is_primary=True, effective_from=(base - timedelta(days=30)).isoformat()
        ),
    ).json()
    # Another supplier becomes primary from today: the first primary term ends yesterday.
    second = client.post(
        f"{API}/suppliers/{other_supplier.id}/terms",
        headers=a.headers,
        json=term_payload(a.product.id, is_primary=True, purchase_price="7.9000"),
    )
    assert second.status_code == 201
    old = client.get(f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers).json()[0]
    assert old["id"] == first["id"]
    assert old["effective_to"] == (base - timedelta(days=1)).isoformat()
    primaries = (
        db.execute(
            select(SupplierProductTerm).where(
                SupplierProductTerm.product_id == a.product.id,
                SupplierProductTerm.is_primary.is_(True),
                SupplierProductTerm.effective_to.is_(None),
            )
        )
        .scalars()
        .all()
    )
    assert len(primaries) == 1
    product = client.get(f"{API}/products/{a.product.id}", headers=a.headers).json()
    assert product["primary_supplier_id"] == str(other_supplier.id)


def test_a_bounded_primary_term_cannot_overlap_another_suppliers_primary(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    other_supplier = factories.make_supplier(db, a.tenant)
    client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(a.product.id, is_primary=True),
    )
    clash = client.post(
        f"{API}/suppliers/{other_supplier.id}/terms",
        headers=a.headers,
        json=term_payload(
            a.product.id,
            is_primary=True,
            effective_to=(today_ist() + timedelta(days=10)).isoformat(),
        ),
    )
    assert clash.status_code == 409
    assert "primary" in clash.json()["error"]["message"]
    # A non primary term for another supplier is fine.
    fine = client.post(
        f"{API}/suppliers/{other_supplier.id}/terms",
        headers=a.headers,
        json=term_payload(a.product.id),
    )
    assert fine.status_code == 201


def test_past_prices_are_history_but_other_fields_can_be_corrected(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    started = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(
            a.product.id, effective_from=(today_ist() - timedelta(days=5)).isoformat()
        ),
    ).json()
    url = f"{API}/supplier-terms/{started['id']}"
    assert (
        client.patch(url, headers=a.headers, json={"purchase_price": "9.0000"}).status_code == 409
    )
    assert (
        client.patch(
            url, headers=a.headers, json={"effective_from": today_ist().isoformat()}
        ).status_code
        == 409
    )
    fixed = client.patch(url, headers=a.headers, json={"pack_size": "12", "moq_units": "24"})
    assert fixed.status_code == 200
    assert (fixed.json()["pack_size"], fixed.json()["moq_units"]) == ("12.000", "24.000")
    ended = client.patch(
        url, headers=a.headers, json={"effective_to": today_ist().isoformat()}
    ).json()
    assert ended["effective_to"] == today_ist().isoformat()
    too_early = client.patch(
        url, headers=a.headers, json={"effective_to": (today_ist() - timedelta(days=9)).isoformat()}
    )
    assert too_early.status_code == 422

    future = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms",
        headers=a.headers,
        json=term_payload(
            a.product.id, effective_from=(today_ist() + timedelta(days=30)).isoformat()
        ),
    ).json()
    repriced = client.patch(
        f"{API}/supplier-terms/{future['id']}", headers=a.headers, json={"purchase_price": "9.2500"}
    )
    assert repriced.status_code == 200
    assert repriced.json()["purchase_price"] == "9.2500"


def test_patching_a_term_cannot_create_an_overlap(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    url = f"{API}/suppliers/{a.supplier.id}/terms"
    base = today_ist()
    first = client.post(
        url,
        headers=a.headers,
        json=term_payload(
            a.product.id,
            effective_from=(base - timedelta(days=20)).isoformat(),
            effective_to=(base - timedelta(days=11)).isoformat(),
        ),
    ).json()
    client.post(
        url,
        headers=a.headers,
        json=term_payload(a.product.id, effective_from=(base - timedelta(days=10)).isoformat()),
    )
    stretched = client.patch(
        f"{API}/supplier-terms/{first['id']}",
        headers=a.headers,
        json={"effective_to": (base - timedelta(days=5)).isoformat()},
    )
    assert stretched.status_code == 409


def test_term_for_a_foreign_product_is_404(client: TestClient, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a, two_tenants.b
    response = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers, json=term_payload(b.product.id)
    )
    assert response.status_code == 404
    assert response.json()["error"]["details"][0]["field"] == "product_id"


# --------------------------------------------------------------------------- 401 and isolation


ANY = uuid.uuid4()
ALL_ROUTES = [
    ("GET", "/suppliers", None),
    ("POST", "/suppliers", {}),
    ("GET", f"/suppliers/{ANY}", None),
    ("PATCH", f"/suppliers/{ANY}", {}),
    ("GET", f"/suppliers/{ANY}/terms", None),
    ("POST", f"/suppliers/{ANY}/terms", {}),
    ("PATCH", f"/supplier-terms/{ANY}", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), ALL_ROUTES)
def test_every_supplier_route_needs_a_token(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert client.request(method, f"{API}{path}", json=body).status_code == 401


def test_tenant_b_cannot_see_or_change_tenant_a_suppliers_and_terms(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    term = client.post(
        f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers, json=term_payload(a.product.id)
    ).json()
    attacks = [
        ("GET", f"/suppliers/{a.supplier.id}", None),
        ("PATCH", f"/suppliers/{a.supplier.id}", {"name": "Hacked"}),
        ("GET", f"/suppliers/{a.supplier.id}/terms", None),
        ("POST", f"/suppliers/{a.supplier.id}/terms", term_payload(b.product.id)),
        ("PATCH", f"/supplier-terms/{term['id']}", {"lead_time_days": 1}),
    ]
    for method, path, body in attacks:
        response = client.request(method, f"{API}{path}", headers=b.headers, json=body)
        assert response.status_code == 404, (method, path, response.text)
    listed = client.get(f"{API}/suppliers", headers=b.headers).json()
    assert {s["id"] for s in listed["items"]} == {str(b.supplier.id)}
    assert (
        client.get(f"{API}/suppliers/{a.supplier.id}", headers=a.headers).json()["name"] != "Hacked"
    )
    unchanged = client.get(f"{API}/suppliers/{a.supplier.id}/terms", headers=a.headers).json()
    assert unchanged[0]["lead_time_days"] is None
