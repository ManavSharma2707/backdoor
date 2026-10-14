"""Bills: pricing, stock allocation, FEFO, duplicates, idempotency, void, returns, listing."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock, now_utc, today_ist, use_clock
from app.core.config import Settings
from app.models.inventory import InventoryMovement
from app.models.ops import AuditLog, IdempotencyKey
from app.models.sales import Sale, SaleLine
from app.services.reconciliation import find_mismatches
from tests import factories
from tests.api.helpers import (
    API,
    line,
    make_batch_with_stock,
    movement_count,
    on_hand,
    post_sale,
    sale_payload,
    stock_up,
    today_iso,
    tracked_product,
)
from tests.conftest import TwoTenants

D = Decimal
SALES = f"{API}/sales"


@pytest.fixture
def shop(db: Session, two_tenants: TwoTenants) -> TwoTenants:
    """Tenant A has 10 packs of its product (price 9.50, MRP 10.00, GST 5 percent)."""
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    return two_tenants


def clean(db: Session, bundle: Any) -> None:
    assert find_mismatches(db, bundle.tenant.id) == []


# --------------------------------------------------------------------------- create and totals


def test_a_simple_bill_is_priced_numbered_and_takes_stock(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    response = post_sale(client, a.headers, sale_payload(line(a.product, "2")))
    assert response.status_code == 201, response.text
    bill = response.json()
    assert bill["bill_no"] == f"B{today_ist():%y%m}-00001"
    assert bill["business_date"] == today_iso()
    assert bill["status"] == "completed"
    assert (bill["subtotal"], bill["discount_total"], bill["total"]) == ("19.00", "0.00", "19.00")
    assert bill["tax_total"] == "0.90"  # 19.00 * 5 / 105, GST is inside the price
    (item,) = bill["lines"]
    assert item["quantity"] == "2.000"
    assert item["unit_price"] == "9.5000"
    assert (item["line_total"], item["tax_rate_pct"], item["tax_amount"]) == (
        "19.00",
        "5.00",
        "0.90",
    )
    assert item["product_sku"] == a.product.sku
    assert item["batch_id"] is None
    assert bill["warnings"] == []

    assert on_hand(db, a.product) == D("8.000")
    move = db.execute(
        select(InventoryMovement).where(InventoryMovement.movement_type == "sale")
    ).scalar_one()
    assert (move.quantity_delta, move.source_type, move.source_id) == (
        D("-2.000"),
        "sale",
        bill["id"],
    )
    assert move.unit_cost == D("5.0000")
    audit = db.execute(
        select(AuditLog).where(AuditLog.tenant_id == a.tenant.id, AuditLog.action == "sale.create")
    ).scalar_one()
    assert audit.entity_id == bill["id"]
    clean(db, a)

    second = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    assert second["bill_no"] == f"B{today_ist():%y%m}-00002"
    assert client.get(f"{SALES}/{bill['id']}", headers=a.headers).json() == {**bill, "warnings": []}


def test_price_override_discount_and_several_lines_add_up(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    second = factories.make_product(
        db,
        a.tenant,
        category=a.category,
        mrp=D("100.00"),
        selling_price=D("90.00"),
        tax_rate_id=factories.tax_rate(db, "GST18").id,
    )
    stock_up(db, a.tenant, a.user, second, "5")
    payload = sale_payload(
        line(a.product, "3", unit_price="9.0000", discount_amount="2.00"),
        line(second, "2", discount_amount="10.00"),
        payment_mode="upi",
    )
    bill = post_sale(client, a.headers, payload).json()
    first, other = bill["lines"]
    assert (first["line_total"], first["discount_amount"], first["unit_price"]) == (
        "25.00",
        "2.00",
        "9.0000",
    )
    assert (other["line_total"], other["tax_amount"]) == ("170.00", "25.93")  # 170 * 18 / 118
    assert bill["subtotal"] == "207.00"  # 27.00 + 180.00
    assert bill["discount_total"] == "12.00"
    assert bill["total"] == "195.00"
    assert bill["tax_total"] == "27.12"  # 1.19 + 25.93
    assert bill["payment_mode"] == "upi"
    clean(db, a)


def test_the_server_computes_money_and_ignores_client_totals(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    payload = sale_payload(line(a.product, "1"), total="0.01", line_total="0.01")
    assert post_sale(client, a.headers, payload).status_code == 422
    body = sale_payload(line(a.product, "1", line_total="0.01"))
    assert post_sale(client, a.headers, body).status_code == 422


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"lines": []}, "lines"),
        ({"payment_mode": "cheque"}, "payment_mode"),
        ({"bill_no": "has space"}, "bill_no"),
        ({"sold_at": "2026-10-13T10:00:00"}, "sold_at"),
        ({"sold_at": "2999-01-01T10:00:00Z"}, "sold_at"),
        ({"sold_at": "2020-01-01T10:00:00Z"}, "sold_at"),
    ],
)
def test_bill_level_validation(
    client: TestClient, shop: TwoTenants, override: dict[str, Any], field: str
) -> None:
    a = shop.a
    payload = sale_payload(line(a.product, "1"))
    payload.update(override)
    response = post_sale(client, a.headers, payload)
    assert response.status_code == 422
    assert any(d["field"].startswith(field) for d in response.json()["error"]["details"])


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"quantity": "0"}, "lines[0].quantity"),
        ({"quantity": "-1"}, "lines[0].quantity"),
        ({"quantity": 2.5}, "lines[0].quantity"),
        ({"quantity": "1.0005"}, "lines[0].quantity"),
        ({"unit_price": "10.01"}, "lines[0].unit_price"),
        ({"unit_price": "-1"}, "lines[0].unit_price"),
        ({"discount_amount": "-1"}, "lines[0].discount_amount"),
        ({"discount_amount": "9.51"}, "lines[0].discount_amount"),
        ({"batch_id": str(uuid.uuid4())}, "lines[0].batch_id"),
    ],
)
def test_line_validation(
    client: TestClient, shop: TwoTenants, override: dict[str, Any], field: str
) -> None:
    a = shop.a
    response = post_sale(client, a.headers, sale_payload({**line(a.product, "1"), **override}))
    assert response.status_code == 422, response.text
    assert any(d["field"] == field for d in response.json()["error"]["details"])


def test_unknown_foreign_and_inactive_products_are_refused(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    stock_up(db, b.tenant, b.user, b.product, "5")
    foreign = post_sale(client, a.headers, sale_payload(line(b.product, "1")))
    assert foreign.status_code == 404
    assert foreign.json()["error"]["details"][0]["field"] == "lines[0].product_id"
    ghost = type("P", (), {"id": uuid.uuid4()})()
    assert post_sale(client, a.headers, sale_payload(line(ghost, "1"))).status_code == 404  # type: ignore[arg-type]
    a.product.is_active = False
    db.flush()
    inactive = post_sale(client, a.headers, sale_payload(line(a.product, "1")))
    assert inactive.status_code == 422
    assert on_hand(db, b.product) == D("5.000")


# --------------------------------------------------------------------------- stock rules


def test_not_enough_stock_is_a_409_that_names_the_products_and_changes_nothing(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    other = factories.make_product(db, a.tenant, name="Tea 250 g", category=a.category)
    stock_up(db, a.tenant, a.user, other, "1")
    before = (
        movement_count(db, a.tenant),
        db.execute(select(func.count()).select_from(Sale)).scalar_one(),
    )
    response = post_sale(client, a.headers, sale_payload(line(a.product, "11"), line(other, "3")))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INSUFFICIENT_STOCK"
    assert a.product.name in error["message"]
    assert "Tea 250 g (1 left)" in error["message"]
    assert [d["field"] for d in error["details"]] == ["lines[0].quantity", "lines[1].quantity"]
    assert "only 10 available, 11 asked for" in error["details"][0]["issue"]
    after = (
        movement_count(db, a.tenant),
        db.execute(select(func.count()).select_from(Sale)).scalar_one(),
    )
    assert after == before
    assert on_hand(db, a.product) == D("10.000")
    audits = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "sale.create")
    ).scalar_one()
    assert audits == 0


def test_selling_exactly_what_is_left_works_and_the_next_sale_is_refused(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    assert post_sale(client, a.headers, sale_payload(line(a.product, "10"))).status_code == 201
    assert on_hand(db, a.product) == D(0)
    assert post_sale(client, a.headers, sale_payload(line(a.product, "0.001"))).status_code == 409


def test_two_lines_for_one_product_share_its_stock(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    refused = post_sale(client, a.headers, sale_payload(line(a.product, "6"), line(a.product, "6")))
    assert refused.status_code == 409
    ok = post_sale(client, a.headers, sale_payload(line(a.product, "6"), line(a.product, "4")))
    assert ok.status_code == 201
    assert len(ok.json()["lines"]) == 2
    assert on_hand(db, a.product) == D(0)
    clean(db, a)


def test_fractional_quantities_work(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    loose = factories.make_product(
        db,
        a.tenant,
        category=a.category,
        base_unit="kg",
        mrp=D("120.00"),
        selling_price=D("110.00"),
    )
    stock_up(db, a.tenant, a.user, loose, "2.5")
    bill = post_sale(client, a.headers, sale_payload(line(loose, "0.750"))).json()
    assert bill["lines"][0]["line_total"] == "82.50"
    assert on_hand(db, loose) == D("1.750")


# --------------------------------------------------------------------------- FEFO


def test_fefo_splits_a_line_across_batches_earliest_expiry_first(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, selling_price=D("9.00"), category=a.category)
    late = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=300, quantity="20", batch_no="LATE"
    )
    early = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=40, quantity="3", batch_no="EARLY"
    )
    middle = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=90, quantity="4", batch_no="MID"
    )

    bill = post_sale(
        client, a.headers, sale_payload(line(product, "9", discount_amount="1.00"))
    ).json()
    parts = [
        (item["batch_no"], item["quantity"], item["discount_amount"], item["line_total"])
        for item in bill["lines"]
    ]
    assert parts == [
        ("EARLY", "3.000", "0.33", "26.67"),
        ("MID", "4.000", "0.45", "35.55"),  # the spare paisa goes to the biggest remainder
        ("LATE", "2.000", "0.22", "17.78"),
    ]
    assert sum(D(p[2]) for p in parts) == D("1.00")
    assert bill["total"] == "80.00"
    assert on_hand(db, product, early) == D(0)
    assert on_hand(db, product, middle) == D(0)
    assert on_hand(db, product, late) == D("18.000")
    assert bill["lines"][0]["expiry_date"] == (today_ist() + timedelta(days=40)).isoformat()
    clean(db, a)


def test_a_chosen_batch_overrides_fefo(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    early = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=30, quantity="5")
    late = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=200, quantity="5")
    bill = post_sale(
        client, a.headers, sale_payload(line(product, "2", batch_id=str(late.id)))
    ).json()
    assert [item["batch_id"] for item in bill["lines"]] == [str(late.id)]
    assert on_hand(db, product, early) == D("5.000")
    assert on_hand(db, product, late) == D("3.000")


def test_expired_stock_is_never_sold(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    expired = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=-1, quantity="5")
    today_batch = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=0, quantity="5"
    )
    fine = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=10, quantity="2")

    short = post_sale(client, a.headers, sale_payload(line(product, "3")))
    assert short.status_code == 409
    assert "(2 left)" in short.json()["error"]["message"]  # 10 on the shelf, 2 that can be sold
    ok = post_sale(client, a.headers, sale_payload(line(product, "2"))).json()
    assert [item["batch_id"] for item in ok["lines"]] == [str(fine.id)]

    forced = post_sale(
        client, a.headers, sale_payload(line(product, "1", batch_id=str(expired.id)))
    )
    assert forced.status_code == 409
    assert forced.json()["error"]["code"] == "BATCH_EXPIRED"
    assert (
        post_sale(
            client, a.headers, sale_payload(line(product, "1", batch_id=str(today_batch.id)))
        ).json()["error"]["code"]
        == "BATCH_EXPIRED"
    )
    assert on_hand(db, product, expired) == D("5.000")


def test_batch_override_rules(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a, two_tenants.b
    product = tracked_product(db, a.tenant, category=a.category)
    held = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=60, quantity="5", status="quarantined"
    )
    ok = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=60, quantity="1")
    other_product = tracked_product(db, b.tenant, category=b.category)
    foreign = make_batch_with_stock(
        db, b.tenant, b.user, other_product, days_to_expiry=60, quantity="5"
    )

    assert (
        post_sale(
            client, a.headers, sale_payload(line(product, "1", batch_id=str(held.id)))
        ).status_code
        == 409
    )
    assert (
        post_sale(
            client, a.headers, sale_payload(line(product, "2", batch_id=str(ok.id)))
        ).status_code
        == 409
    )
    assert (
        post_sale(
            client, a.headers, sale_payload(line(product, "1", batch_id=str(foreign.id)))
        ).status_code
        == 404
    )
    # FEFO also skips the quarantined batch.
    bill = post_sale(client, a.headers, sale_payload(line(product, "1"))).json()
    assert bill["lines"][0]["batch_id"] == str(ok.id)
    # A batch cannot be named for a product that is not tracked by batch.
    plain = factories.make_product(db, a.tenant, category=a.category)
    stock_up(db, a.tenant, a.user, plain, "3")
    assert (
        post_sale(
            client, a.headers, sale_payload(line(plain, "1", batch_id=str(ok.id)))
        ).status_code
        == 422
    )


# --------------------------------------------------------------------------- bill numbers and duplicates


def test_bill_numbers_can_be_chosen_but_not_reused(
    client: TestClient, shop: TwoTenants, db: Session
) -> None:
    a, b = shop.a, shop.b
    stock_up(db, b.tenant, b.user, b.product, "5")
    first = post_sale(client, a.headers, sale_payload(line(a.product, "1"), bill_no="INV-1"))
    assert first.status_code == 201
    assert first.json()["bill_no"] == "INV-1"
    clash = post_sale(client, a.headers, sale_payload(line(a.product, "1"), bill_no="INV-1"))
    assert clash.status_code == 409
    assert clash.json()["error"]["details"][0]["field"] == "bill_no"
    assert on_hand(db, a.product) == D("9.000")
    # Another tenant has its own numbers.
    assert (
        post_sale(
            client, b.headers, sale_payload(line(b.product, "1"), bill_no="INV-1")
        ).status_code
        == 201
    )
    # Automatic numbers carry on after custom ones.
    auto = post_sale(client, a.headers, sale_payload(line(a.product, "2"))).json()
    assert auto["bill_no"].endswith("-00001")


def test_an_identical_basket_within_two_minutes_saves_with_a_warning(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    first = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    assert first["warnings"] == []
    again = post_sale(client, a.headers, sale_payload(line(a.product, "1")))
    assert again.status_code == 201  # a warning, never a refusal
    (warning,) = again.json()["warnings"]
    assert warning["code"] == "POSSIBLE_DUPLICATE"
    assert warning["sale_id"] == first["id"]
    assert first["bill_no"] in warning["message"]
    assert on_hand(db, a.product) == D("8.000")


def test_duplicate_warning_needs_the_same_basket_total_window_and_status(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    other = factories.make_product(db, a.tenant, category=a.category)
    stock_up(db, a.tenant, a.user, other, "10")
    base = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    # Different basket, same total: no warning.
    assert post_sale(client, a.headers, sale_payload(line(other, "1"))).json()["warnings"] == []
    # Same basket at a different price (so a different total): no warning.
    discounted = post_sale(
        client, a.headers, sale_payload(line(a.product, "1", discount_amount="1.00"))
    )
    assert discounted.json()["warnings"] == []
    # Same basket but sold five minutes later: outside the window.
    later = (now_utc() + timedelta(minutes=4)).isoformat()
    assert (
        post_sale(client, a.headers, sale_payload(line(a.product, "1"), sold_at=later)).json()[
            "warnings"
        ]
        == []
    )
    # A voided bill does not count.
    client.post(f"{SALES}/{base['id']}/void", headers=a.headers, json={"reason": "wrong entry"})
    third = post_sale(
        client,
        a.headers,
        sale_payload(line(a.product, "1"), sold_at=(now_utc() + timedelta(seconds=1)).isoformat()),
    )
    assert third.json()["warnings"] == [] or third.json()["warnings"][0]["sale_id"] != base["id"]


# --------------------------------------------------------------------------- idempotency


def test_the_same_key_and_body_replays_the_stored_response(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    payload = sale_payload(line(a.product, "2"))
    first = post_sale(client, a.headers, payload, **{"Idempotency-Key": "key-aaaa-0001"})
    assert first.status_code == 201
    assert "idempotent-replay" not in first.headers
    replay = post_sale(client, a.headers, payload, **{"Idempotency-Key": "key-aaaa-0001"})
    assert replay.status_code == 201
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json() == first.json()
    assert db.execute(select(func.count()).select_from(Sale)).scalar_one() == 1
    assert movement_count(db, a.tenant, "sale") == 1
    assert on_hand(db, a.product) == D("8.000")
    stored = db.execute(select(IdempotencyKey)).scalar_one()
    assert (stored.endpoint, stored.response_status, stored.key) == (
        "POST /sales",
        201,
        "key-aaaa-0001",
    )
    assert stored.expires_at - stored.created_at > timedelta(hours=47)


def test_the_same_key_with_a_different_body_is_a_422(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    post_sale(
        client,
        a.headers,
        sale_payload(line(a.product, "2")),
        **{"Idempotency-Key": "key-bbbb-0002"},
    )
    clash = post_sale(
        client,
        a.headers,
        sale_payload(line(a.product, "3")),
        **{"Idempotency-Key": "key-bbbb-0002"},
    )
    assert clash.status_code == 422
    assert clash.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    assert on_hand(db, a.product) == D("8.000")


def test_key_order_of_fields_does_not_change_the_hash(client: TestClient, shop: TwoTenants) -> None:
    a = shop.a
    one = {"payment_mode": "cash", "lines": [{"product_id": str(a.product.id), "quantity": "1"}]}
    two = {
        "lines": [{"quantity": "1.000", "product_id": str(a.product.id)}],
        "payment_mode": "cash",
    }
    first = post_sale(client, a.headers, one, **{"Idempotency-Key": "key-cccc-0003"})
    replay = post_sale(client, a.headers, two, **{"Idempotency-Key": "key-cccc-0003"})
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json() == first.json()


def test_keys_are_per_tenant_and_per_operation(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    stock_up(db, b.tenant, b.user, b.product, "5")
    key = {"Idempotency-Key": "shared-key-01"}
    assert (
        post_sale(client, a.headers, sale_payload(line(a.product, "1")), **key).status_code == 201
    )
    other = post_sale(client, b.headers, sale_payload(line(b.product, "1")), **key)
    assert other.status_code == 201
    assert "idempotent-replay" not in other.headers
    assert other.json()["id"] != client.get(f"{SALES}", headers=a.headers).json()["items"][0]["id"]


def test_a_refused_request_does_not_burn_its_key(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    key = {"Idempotency-Key": "key-dddd-0004"}
    refused = post_sale(client, a.headers, sale_payload(line(a.product, "99")), **key)
    assert refused.status_code == 409
    assert db.execute(select(func.count()).select_from(IdempotencyKey)).scalar_one() == 0
    stock_up(db, a.tenant, a.user, a.product, "100")
    assert (
        post_sale(client, a.headers, sale_payload(line(a.product, "99")), **key).status_code == 201
    )


def test_without_a_key_every_request_is_a_new_bill(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    for _ in range(2):
        assert post_sale(client, a.headers, sale_payload(line(a.product, "1"))).status_code == 201
    assert db.execute(select(func.count()).select_from(Sale)).scalar_one() == 2


@pytest.mark.parametrize("key", ["short", "x" * 65, "has space in it", "semi;colon;key"])
def test_bad_idempotency_keys_are_a_422(client: TestClient, shop: TwoTenants, key: str) -> None:
    response = post_sale(
        client, shop.a.headers, sale_payload(line(shop.a.product, "1")), **{"Idempotency-Key": key}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "Idempotency-Key"


def test_keys_expire_after_48_hours(
    client: TestClient, db: Session, shop: TwoTenants, test_settings: Settings
) -> None:
    a = shop.a
    key = {"Idempotency-Key": "key-eeee-0005"}
    payload = sale_payload(line(a.product, "1"))

    def post_now() -> Any:
        # Access tokens last 15 minutes, so sign a fresh one for the moved clock.
        return post_sale(client, factories.auth_headers(test_settings, a.user), payload, **key)

    with use_clock(FakeClock(now_utc())) as clock:
        first = post_now().json()
        clock.advance(timedelta(hours=47))
        assert post_now().headers["idempotent-replay"] == "true"
        clock.advance(timedelta(hours=2))
        again = post_now()
        assert again.status_code == 201
        assert "idempotent-replay" not in again.headers
        assert again.json()["id"] != first["id"]
    assert db.execute(select(func.count()).select_from(Sale)).scalar_one() == 2


# --------------------------------------------------------------------------- void


def test_void_reverses_every_movement_and_leaves_the_originals(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    product = tracked_product(db, a.tenant, category=a.category)
    early = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=30, quantity="3")
    late = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=90, quantity="10")
    before = {b.id: on_hand(db, product, b) for b in (early, late)}
    bill = post_sale(
        client, a.headers, sale_payload(line(product, "5"), line(a.product, "2"))
    ).json()
    originals = db.execute(
        select(InventoryMovement.id, InventoryMovement.quantity_delta)
        .where(InventoryMovement.movement_type == "sale")
        .order_by(InventoryMovement.id)
    ).all()
    assert len(originals) == 3  # two batches of the tracked product and one plain line

    voided = client.post(
        f"{SALES}/{bill['id']}/void", headers=a.headers, json={"reason": "Customer left"}
    )
    assert voided.status_code == 200
    body = voided.json()
    assert (body["status"], body["void_reason"]) == ("void", "Customer left")
    assert body["voided_at"] is not None
    assert body["total"] == bill["total"]  # the bill itself is unchanged

    assert {b.id: on_hand(db, product, b) for b in (early, late)} == before
    assert on_hand(db, a.product) == D("10.000")
    still_there = db.execute(
        select(InventoryMovement.id, InventoryMovement.quantity_delta)
        .where(InventoryMovement.movement_type == "sale")
        .order_by(InventoryMovement.id)
    ).all()
    assert still_there == originals
    reversals = (
        db.execute(
            select(InventoryMovement)
            .where(InventoryMovement.movement_type == "void_reversal")
            .order_by(InventoryMovement.id)
        )
        .scalars()
        .all()
    )
    assert [r.reverses_movement_id for r in reversals] == [o.id for o in originals]
    assert [r.quantity_delta for r in reversals] == [-o.quantity_delta for o in originals]
    assert all(r.source_type == "void" and r.source_id == bill["id"] for r in reversals)
    assert db.execute(select(func.count()).select_from(SaleLine)).scalar_one() == 3
    audit = db.execute(select(AuditLog).where(AuditLog.action == "sale.void")).scalar_one()
    assert audit.after["reason"] == "Customer left"
    clean(db, a)


def test_a_bill_can_only_be_voided_once_and_needs_a_reason(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    url = f"{SALES}/{bill['id']}/void"
    assert client.post(url, headers=a.headers, json={}).status_code == 422
    assert client.post(url, headers=a.headers, json={"reason": "x"}).status_code == 422
    assert client.post(url, headers=a.headers, json={"reason": "wrong item"}).status_code == 200
    again = client.post(url, headers=a.headers, json={"reason": "wrong item"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "CONFLICT"


def test_a_voided_bill_does_not_count_in_summaries_but_stays_in_the_list(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    keep = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    gone = post_sale(client, a.headers, sale_payload(line(a.product, "2"))).json()
    client.post(f"{SALES}/{gone['id']}/void", headers=a.headers, json={"reason": "wrong item"})
    summary = client.get(f"{SALES}/summary", headers=a.headers).json()
    assert (summary["bills"], summary["sales"]) == (1, keep["total"])
    listed = client.get(SALES, headers=a.headers).json()
    assert {item["status"] for item in listed["items"]} == {"completed", "void"}
    only_void = client.get(SALES, headers=a.headers, params={"status": "void"}).json()
    assert [i["id"] for i in only_void["items"]] == [gone["id"]]


# --------------------------------------------------------------------------- returns


def test_restocked_return_puts_goods_back_and_refunds_the_line_share(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    bill = post_sale(
        client, a.headers, sale_payload(line(a.product, "4", discount_amount="2.00"))
    ).json()
    (item,) = bill["lines"]
    assert item["line_total"] == "36.00"
    response = client.post(
        f"{SALES}/{bill['id']}/returns",
        headers=a.headers,
        json={
            "reason": "Customer changed mind",
            "lines": [{"sale_line_id": item["id"], "quantity": "1", "disposition": "restock"}],
        },
    )
    assert response.status_code == 201, response.text
    ret = response.json()
    assert ret["return_no"] == f"R{today_ist():%y%m}-0001"
    assert ret["refund_total"] == "9.00"
    assert ret["bill_no"] == bill["bill_no"]
    assert ret["lines"][0]["disposition"] == "restock"
    assert on_hand(db, a.product) == D("7.000")  # 10 - 4 + 1
    moves = db.execute(
        select(InventoryMovement.movement_type, InventoryMovement.quantity_delta).where(
            InventoryMovement.source_type == "sale_return"
        )
    ).all()
    assert moves == [("return_in", D("1.000"))]
    refreshed = client.get(f"{SALES}/{bill['id']}", headers=a.headers).json()
    assert refreshed["lines"][0]["returned_qty"] == "1.000"
    assert [r["id"] for r in refreshed["returns"]] == [ret["id"]]
    clean(db, a)


def test_damaged_and_expired_returns_come_in_and_are_written_off(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "5"))).json()
    line_id = bill["lines"][0]["id"]
    response = client.post(
        f"{SALES}/{bill['id']}/returns",
        headers=a.headers,
        json={
            "reason": "Packet torn",
            "lines": [
                {"sale_line_id": line_id, "quantity": "1", "disposition": "damaged"},
                {"sale_line_id": line_id, "quantity": "2", "disposition": "expired"},
            ],
        },
    )
    assert response.status_code == 201
    assert on_hand(db, a.product) == D("5.000")  # nothing went back on the shelf
    moves = db.execute(
        select(InventoryMovement.movement_type, InventoryMovement.quantity_delta)
        .where(InventoryMovement.source_type == "sale_return")
        .order_by(InventoryMovement.id)
    ).all()
    assert moves == [
        ("return_in", D("1.000")),
        ("damage", D("-1.000")),
        ("return_in", D("2.000")),
        ("expiry_writeoff", D("-2.000")),
    ]
    assert (
        client.get(f"{SALES}/{bill['id']}", headers=a.headers).json()["lines"][0]["returned_qty"]
        == "3.000"
    )
    clean(db, a)


def test_a_return_goes_back_to_the_batch_that_was_sold(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    early = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=30, quantity="2")
    late = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=90, quantity="5")
    bill = post_sale(client, a.headers, sale_payload(line(product, "3"))).json()
    second_part = bill["lines"][1]  # the part taken from the later batch
    client.post(
        f"{SALES}/{bill['id']}/returns",
        headers=a.headers,
        json={
            "reason": "No longer needed",
            "lines": [
                {"sale_line_id": second_part["id"], "quantity": "1", "disposition": "restock"}
            ],
        },
    )
    assert on_hand(db, product, early) == D(0)
    assert on_hand(db, product, late) == D("5.000")
    clean(db, a)


def test_returns_cannot_exceed_what_was_sold(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "3"))).json()
    line_id = bill["lines"][0]["id"]
    url = f"{SALES}/{bill['id']}/returns"

    def ask(quantity: str, *more: str) -> Any:
        lines = [
            {"sale_line_id": line_id, "quantity": q, "disposition": "restock"}
            for q in (quantity, *more)
        ]
        return client.post(
            url, headers=a.headers, json={"reason": "Customer returned", "lines": lines}
        )

    over = ask("3.001")
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "RETURN_EXCEEDS_SOLD"
    assert ask("2", "2").status_code == 409  # the lines add up to more than was sold
    assert on_hand(db, a.product) == D("7.000")
    assert ask("2").status_code == 201
    assert ask("1.001").status_code == 409
    assert ask("1").status_code == 201
    assert ask("0.001").status_code == 409
    refreshed = client.get(f"{SALES}/{bill['id']}", headers=a.headers).json()
    assert refreshed["lines"][0]["returned_qty"] == "3.000"
    assert sum(D(r["refund_total"]) for r in refreshed["returns"]) == D(bill["total"])
    assert [r["return_no"][-4:] for r in refreshed["returns"]] == ["0001", "0002"]
    clean(db, a)


def test_return_validation_and_state_rules(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    stock_up(db, b.tenant, b.user, b.product, "5")
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "2"))).json()
    other_bill = post_sale(client, b.headers, sale_payload(line(b.product, "1"))).json()
    url = f"{SALES}/{bill['id']}/returns"
    good_line = bill["lines"][0]["id"]
    body = {
        "reason": "Customer returned",
        "lines": [{"sale_line_id": good_line, "quantity": "1", "disposition": "restock"}],
    }

    assert client.post(url, headers=a.headers, json={**body, "reason": "x"}).status_code == 422
    assert client.post(url, headers=a.headers, json={**body, "lines": []}).status_code == 422
    bad_disposition = {**body, "lines": [{**body["lines"][0], "disposition": "lost"}]}
    assert client.post(url, headers=a.headers, json=bad_disposition).status_code == 422
    # A line of another bill (even another tenant's) is not found.
    foreign_line = {
        **body,
        "lines": [{**body["lines"][0], "sale_line_id": other_bill["lines"][0]["id"]}],
    }
    assert client.post(url, headers=a.headers, json=foreign_line).status_code == 404

    client.post(f"{SALES}/{bill['id']}/void", headers=a.headers, json={"reason": "wrong item"})
    on_void = client.post(url, headers=a.headers, json=body)
    assert on_void.status_code == 409


def test_a_bill_with_returns_cannot_be_voided(client: TestClient, shop: TwoTenants) -> None:
    a = shop.a
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "2"))).json()
    client.post(
        f"{SALES}/{bill['id']}/returns",
        headers=a.headers,
        json={
            "reason": "Customer returned",
            "lines": [
                {"sale_line_id": bill["lines"][0]["id"], "quantity": "1", "disposition": "restock"}
            ],
        },
    )
    refused = client.post(
        f"{SALES}/{bill['id']}/void", headers=a.headers, json={"reason": "wrong item"}
    )
    assert refused.status_code == 409
    assert "returns" in refused.json()["error"]["message"]


def test_returns_are_idempotent(client: TestClient, db: Session, shop: TwoTenants) -> None:
    a = shop.a
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "3"))).json()
    url = f"{SALES}/{bill['id']}/returns"
    body = {
        "reason": "Customer returned",
        "lines": [
            {"sale_line_id": bill["lines"][0]["id"], "quantity": "1", "disposition": "restock"}
        ],
    }
    key = {"Idempotency-Key": "ret-key-0001"}
    first = client.post(url, headers={**a.headers, **key}, json=body)
    replay = client.post(url, headers={**a.headers, **key}, json=body)
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json() == first.json()
    assert on_hand(db, a.product) == D("8.000")
    different = client.post(
        url, headers={**a.headers, **key}, json={**body, "reason": "Another reason"}
    )
    assert different.status_code == 422
    # The same key on another bill is a different operation.
    other = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    ok = client.post(
        f"{SALES}/{other['id']}/returns",
        headers={**a.headers, **key},
        json={**body, "lines": [{**body["lines"][0], "sale_line_id": other["lines"][0]["id"]}]},
    )
    assert ok.status_code == 201
    assert "idempotent-replay" not in ok.headers


# --------------------------------------------------------------------------- list and summary


def test_list_filters_by_date_status_and_bill_number(client: TestClient, shop: TwoTenants) -> None:
    a = shop.a
    old = post_sale(
        client,
        a.headers,
        sale_payload(
            line(a.product, "1"),
            sold_at=(now_utc() - timedelta(days=10)).isoformat(),
            bill_no="OLD-1",
        ),
    ).json()
    new = post_sale(client, a.headers, sale_payload(line(a.product, "2"), bill_no="NEW-1")).json()

    def ids(**params: Any) -> list[str]:
        body = client.get(SALES, headers=a.headers, params=params).json()
        return [item["id"] for item in body["items"]]

    assert ids() == [new["id"], old["id"]]  # newest first
    since = (today_ist() - timedelta(days=3)).isoformat()
    assert ids(**{"from": since}) == [new["id"]]
    assert ids(to=since) == [old["id"]]
    assert ids(q="old") == [old["id"]]
    assert ids(q="%") == []
    assert ids(sort="total:asc") == [old["id"], new["id"]]
    body = client.get(SALES, headers=a.headers, params={"page_size": 1, "page": 2}).json()
    assert (body["total"], len(body["items"]), body["page"]) == (2, 1, 2)
    item = client.get(SALES, headers=a.headers).json()["items"][0]
    assert item["items"] == 1
    assert item["returned_total"] == "0.00"


def test_summary_groups_by_day_and_week_and_nets_returns(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    for days, qty in ((0, "2"), (0, "1"), (8, "1")):
        post_sale(
            client,
            a.headers,
            sale_payload(
                line(a.product, qty), sold_at=(now_utc() - timedelta(days=days)).isoformat()
            ),
        )
    first = client.get(SALES, headers=a.headers, params={"sort": "sold_at:desc"}).json()["items"][0]
    detail = client.get(f"{SALES}/{first['id']}", headers=a.headers).json()
    client.post(
        f"{SALES}/{first['id']}/returns",
        headers=a.headers,
        json={
            "reason": "Customer returned",
            "lines": [
                {
                    "sale_line_id": detail["lines"][0]["id"],
                    "quantity": "1",
                    "disposition": "restock",
                }
            ],
        },
    )
    daily = client.get(f"{SALES}/summary", headers=a.headers, params={"group": "day"}).json()
    assert daily["bills"] == 3
    assert len(daily["series"]) == 2
    today_point = daily["series"][-1]
    assert today_point["period"] == today_iso()
    assert today_point["bills"] == 2
    assert today_point["returns"] == "9.50"
    weekly = client.get(f"{SALES}/summary", headers=a.headers, params={"group": "week"}).json()
    assert all(
        __import__("datetime").date.fromisoformat(p["period"]).weekday() == 0
        for p in weekly["series"]
    )
    assert sum(p["bills"] for p in weekly["series"]) == 3
    assert weekly["returns"] == "9.50"
    assert (
        client.get(f"{SALES}/summary", headers=a.headers, params={"group": "month"}).status_code
        == 422
    )


# --------------------------------------------------------------------------- 401 and isolation


ANY = uuid.uuid4()
ALL_ROUTES = [
    ("POST", "/sales", {}),
    ("GET", "/sales", None),
    ("GET", "/sales/summary", None),
    ("GET", f"/sales/{ANY}", None),
    ("POST", f"/sales/{ANY}/void", {}),
    ("POST", f"/sales/{ANY}/returns", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), ALL_ROUTES)
def test_every_sales_route_needs_a_token(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert client.request(method, f"{API}{path}", json=body).status_code == 401


def test_tenant_b_cannot_see_void_or_return_tenant_a_bills(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    stock_up(db, b.tenant, b.user, b.product, "5")
    bill = post_sale(client, a.headers, sale_payload(line(a.product, "2"))).json()
    line_id = bill["lines"][0]["id"]
    attacks = [
        ("GET", f"/sales/{bill['id']}", None),
        ("POST", f"/sales/{bill['id']}/void", {"reason": "Not yours to void"}),
        (
            "POST",
            f"/sales/{bill['id']}/returns",
            {
                "reason": "Not yours to return",
                "lines": [{"sale_line_id": line_id, "quantity": "1", "disposition": "restock"}],
            },
        ),
    ]
    for method, path, body in attacks:
        response = client.request(method, f"{API}{path}", headers=b.headers, json=body)
        assert response.status_code == 404, (method, path, response.text)
    assert client.get(SALES, headers=b.headers).json()["items"] == []
    assert client.get(f"{SALES}/summary", headers=b.headers).json()["bills"] == 0
    untouched = client.get(f"{SALES}/{bill['id']}", headers=a.headers).json()
    assert untouched["status"] == "completed"
    assert untouched["returns"] == []
    assert on_hand(db, a.product) == D("8.000")
    assert on_hand(db, b.product) == D("5.000")
