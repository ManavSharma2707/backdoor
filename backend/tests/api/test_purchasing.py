"""Purchase orders, the state machine and goods receipts."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.models.inventory import ProductBatch, StockBalance
from app.models.ops import AuditLog
from app.models.purchasing import PurchaseOrder
from app.services.reconciliation import find_mismatches
from tests import factories
from tests.api.helpers import API, movement_count, on_hand, stock_up, tracked_product
from tests.conftest import TwoTenants

D = Decimal
ORDERS = f"{API}/purchase-orders"
RECEIPTS = f"{API}/receipts"


@pytest.fixture
def shop(db: Session, two_tenants: TwoTenants) -> TwoTenants:
    """Tenant A buys its product from its supplier at 8.0000, pack of 10."""
    a = two_tenants.a
    factories.make_terms(db, a.tenant, a.supplier, a.product, pack_size=D(10), is_primary=True)
    return two_tenants


def new_order(
    client: TestClient, bundle: Any, *items: tuple[Any, str] | tuple[Any, str, str], **extra: Any
) -> dict[str, Any]:
    lines = []
    for item in items:
        body: dict[str, Any] = {"product_id": str(item[0].id), "quantity_ordered": item[1]}
        if len(item) == 3:
            body["unit_cost"] = item[2]
        lines.append(body)
    response = client.post(
        ORDERS,
        headers=bundle.headers,
        json={"supplier_id": str(bundle.supplier.id), "lines": lines, **extra},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def sent_order(client: TestClient, bundle: Any, *items: tuple[Any, str]) -> dict[str, Any]:
    order = new_order(client, bundle, *items)
    response = client.post(f"{ORDERS}/{order['id']}/send", headers=bundle.headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def receive(
    client: TestClient,
    bundle: Any,
    order: dict[str, Any],
    *entries: tuple[int, str] | dict[str, Any],
    **extra: Any,
) -> Any:
    lines = []
    for entry in entries:
        if isinstance(entry, dict):
            lines.append(entry)
            continue
        index, quantity = entry
        lines.append(
            {
                "po_line_id": order["lines"][index]["id"],
                "quantity_received": quantity,
                "unit_cost": order["lines"][index]["unit_cost"],
            }
        )
    headers = {**bundle.headers, **extra.pop("headers", {})}
    return client.post(
        f"{ORDERS}/{order['id']}/receipts", headers=headers, json={"lines": lines, **extra}
    )


# --------------------------------------------------------------------------- create


def test_create_defaults_cost_pack_and_expected_date_from_the_terms(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    a.supplier.default_lead_time_days = 2
    db.flush()
    order = new_order(client, a, (a.product, "30"))
    assert order["po_number"] == f"PO{today_ist():%y%m}-0001"
    assert order["status"] == "draft"
    assert order["order_date"] == today_ist().isoformat()
    assert order["expected_date"] == (today_ist() + timedelta(days=2)).isoformat()
    assert order["subtotal_estimated"] == "240.00"
    (line,) = order["lines"]
    assert (line["unit_cost"], line["pack_size"], line["quantity_open"]) == (
        "8.0000",
        "10.000",
        "30.000",
    )
    assert (line["line_value"], line["quantity_received"]) == ("240.00", "0.000")
    assert order["is_overdue"] is False
    assert [e["event"] for e in order["timeline"]] == ["created"]
    assert new_order(client, a, (a.product, "10"))["po_number"].endswith("-0002")
    audit = (
        db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == a.tenant.id, AuditLog.action == "po.create"
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.after["lines"] == 1


def test_expected_date_lands_on_a_supplier_delivery_day(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    a.supplier.delivery_weekdays = [2, 5]
    db.flush()
    expected = new_order(client, a, (a.product, "10"))["expected_date"]
    day = today_ist() + timedelta(days=3)  # the business default lead time
    assert expected >= day.isoformat()
    assert __import__("datetime").date.fromisoformat(expected).isoweekday() in {2, 5}


def test_an_explicit_cost_and_expected_date_win(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    when = (today_ist() + timedelta(days=9)).isoformat()
    order = new_order(client, a, (a.product, "5", "7.5000"), expected_date=when, notes="Call first")
    assert order["lines"][0]["unit_cost"] == "7.5000"
    assert order["expected_date"] == when
    assert order["notes"] == "Call first"
    assert order["subtotal_estimated"] == "37.50"


def test_a_product_with_no_price_is_a_409_that_names_it(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    unpriced = factories.make_product(db, a.tenant, name="Tea 250 g", category=a.category)
    response = client.post(
        ORDERS,
        headers=a.headers,
        json={
            "supplier_id": str(a.supplier.id),
            "lines": [
                {"product_id": str(a.product.id), "quantity_ordered": "10"},
                {"product_id": str(unpriced.id), "quantity_ordered": "10"},
            ],
        },
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "MISSING_SUPPLIER_OR_COST"
    assert error["details"] == [{"field": "lines[1].unit_cost", "issue": "no price for Tea 250 g"}]
    assert db.execute(select(PurchaseOrder)).first() is None


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"lines": []}, 422),
        ({"expected_date": "2020-01-01"}, 422),
        ({"surprise": 1}, 422),
    ],
)
def test_create_validation(
    client: TestClient, shop: TwoTenants, override: dict[str, Any], status: int
) -> None:
    a = shop.a
    body = {
        "supplier_id": str(a.supplier.id),
        "lines": [{"product_id": str(a.product.id), "quantity_ordered": "10"}],
    }
    body.update(override)
    assert client.post(ORDERS, headers=a.headers, json=body).status_code == status


def test_line_rules(client: TestClient, db: Session, shop: TwoTenants) -> None:
    a, b = shop.a, shop.b
    base = {"supplier_id": str(a.supplier.id)}
    line = {"product_id": str(a.product.id), "quantity_ordered": "10"}

    def post(**changes: Any) -> Any:
        return client.post(ORDERS, headers=a.headers, json={**base, "lines": [{**line, **changes}]})

    assert post(quantity_ordered="0").status_code == 422
    assert post(quantity_ordered=5.5).status_code == 422
    assert post(unit_cost="-1").status_code == 422
    twice = client.post(ORDERS, headers=a.headers, json={**base, "lines": [line, line]})
    assert twice.status_code == 422
    assert twice.json()["error"]["details"][0]["field"] == "lines[1].product_id"
    assert post(product_id=str(b.product.id)).status_code == 404
    a.product.is_active = False
    db.flush()
    assert post().status_code == 422


def test_supplier_must_belong_to_the_tenant_and_be_active(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    line = [{"product_id": str(a.product.id), "quantity_ordered": "10", "unit_cost": "8"}]
    foreign = client.post(
        ORDERS, headers=a.headers, json={"supplier_id": str(b.supplier.id), "lines": line}
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["details"][0]["field"] == "supplier_id"
    a.supplier.is_active = False
    db.flush()
    off = client.post(
        ORDERS, headers=a.headers, json={"supplier_id": str(a.supplier.id), "lines": line}
    )
    assert off.status_code == 422


def test_a_draft_can_be_edited_and_nothing_else(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    other = factories.make_product(db, a.tenant, category=a.category)
    order = new_order(client, a, (a.product, "10"))
    url = f"{ORDERS}/{order['id']}"
    edited = client.patch(
        url,
        headers=a.headers,
        json={
            "notes": "Updated",
            "lines": [
                {"product_id": str(other.id), "quantity_ordered": "4", "unit_cost": "2.5"},
                {"product_id": str(a.product.id), "quantity_ordered": "20"},
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["notes"] == "Updated"
    assert body["subtotal_estimated"] == "170.00"  # 4 * 2.50 + 20 * 8.00
    assert len(body["lines"]) == 2
    assert client.patch(url, headers=a.headers, json={"lines": None}).status_code == 422
    assert (
        client.patch(url, headers=a.headers, json={"expected_date": "2020-01-01"}).status_code
        == 422
    )
    client.post(f"{url}/send", headers=a.headers)
    refused = client.patch(url, headers=a.headers, json={"notes": "Too late"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "PO_STATE_INVALID"


# --------------------------------------------------------------------------- state machine


def test_the_state_machine_end_to_end(client: TestClient, db: Session, shop: TwoTenants) -> None:
    a = shop.a
    order = new_order(client, a, (a.product, "10"))
    url = f"{ORDERS}/{order['id']}"

    def act(action: str, **kw: Any) -> Any:
        return client.post(f"{url}/{action}", headers=a.headers, **kw)

    assert act("close").status_code == 409  # a draft cannot be closed
    assert act("send").json()["status"] == "sent"
    sent = client.get(url, headers=a.headers).json()
    assert sent["sent_at"] is not None
    assert [e["event"] for e in sent["timeline"]] == ["created", "sent"]
    assert act("send").status_code == 409
    assert act("close").json()["status"] == "closed"
    assert act("cancel").status_code == 409
    assert act("send").status_code == 409
    actions = (
        db.execute(
            select(AuditLog.action)
            .where(AuditLog.tenant_id == a.tenant.id, AuditLog.action.like("po.%"))
            .order_by(AuditLog.id)
        )
        .scalars()
        .all()
    )
    assert actions == ["po.create", "po.send", "po.close"]


def test_cancel_records_a_reason_and_a_cancelled_order_is_not_incoming(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "10"))
    cancelled = client.post(
        f"{ORDERS}/{order['id']}/cancel", headers=a.headers, json={"reason": "Found a better price"}
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert (body["status"], body["cancel_reason"]) == ("cancelled", "Found a better price")
    assert body["cancelled_at"] is not None
    assert receive(client, a, order, (0, "1")).status_code == 409
    assert client.post(f"{ORDERS}/{order['id']}/cancel", headers=a.headers).status_code == 409
    plain = new_order(client, a, (a.product, "10"))
    assert (
        client.post(f"{ORDERS}/{plain['id']}/cancel", headers=a.headers).json()["status"]
        == "cancelled"
    )


# --------------------------------------------------------------------------- receipts


def test_partial_then_complete_receipt(client: TestClient, db: Session, shop: TwoTenants) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "30"))
    first = receive(client, a, order, (0, "10"), invoice_no="INV-77", invoice_total="80.00")
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert receipt["receipt_no"] == f"GR{today_ist():%y%m}-0001"
    assert receipt["po_status"] == "partially_received"
    assert receipt["po_number"] == order["po_number"]
    assert receipt["lines_total"] == "80.00"
    assert [w["code"] for w in receipt["warnings"]] == ["SHORT_RECEIPT"]
    assert "20" in receipt["warnings"][0]["message"]
    assert on_hand(db, a.product) == D("10.000")

    detail = client.get(f"{ORDERS}/{order['id']}", headers=a.headers).json()
    assert detail["status"] == "partially_received"
    assert (detail["lines"][0]["quantity_received"], detail["lines"][0]["quantity_open"]) == (
        "10.000",
        "20.000",
    )
    assert [r["receipt_no"] for r in detail["receipts"]] == [receipt["receipt_no"]]
    assert [e["event"] for e in detail["timeline"]] == ["created", "sent", "received"]

    second = receive(client, a, order, (0, "20"))
    assert second.json()["po_status"] == "received"
    assert second.json()["warnings"] == []
    assert on_hand(db, a.product) == D("30.000")
    final = client.get(f"{ORDERS}/{order['id']}", headers=a.headers).json()
    assert final["status"] == "received"
    assert len(final["receipts"]) == 2
    assert movement_count(db, a.tenant, "receipt") == 2
    assert find_mismatches(db, a.tenant.id) == []
    assert (
        client.post(f"{ORDERS}/{order['id']}/close", headers=a.headers).json()["status"] == "closed"
    )
    assert receive(client, a, order, (0, "1")).status_code == 409


def test_receiving_updates_the_weighted_average_cost(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    stock_up(db, a.tenant, a.user, a.product, "10", cost="8.0000")
    order = sent_order(client, a, (a.product, "30"))
    response = receive(
        client,
        a,
        order,
        {"po_line_id": order["lines"][0]["id"], "quantity_received": "30", "unit_cost": "9.0000"},
    )
    assert response.status_code == 201
    balance = db.execute(
        select(StockBalance).where(StockBalance.product_id == a.product.id)
    ).scalar_one()
    assert (balance.on_hand, balance.avg_unit_cost) == (D("40.000"), D("8.7500"))


def test_receiving_more_than_ordered_needs_an_exception_with_a_note(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "10"))
    refused = receive(client, a, order, (0, "12"))
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "RECEIPT_EXCEEDS_ORDER"
    assert "12 arrived, 10 still open" in error["details"][0]["issue"]
    assert on_hand(db, a.product) == D(0)
    no_note = receive(client, a, order, (0, "12"), is_exception=True)
    assert no_note.status_code == 422
    allowed = receive(
        client, a, order, (0, "12"), is_exception=True, exception_note="Supplier sent extra cartons"
    )
    assert allowed.status_code == 201
    body = allowed.json()
    assert body["is_exception"] is True
    assert "OVER_RECEIPT" in [w["code"] for w in body["warnings"]]
    assert body["po_status"] == "received"
    assert on_hand(db, a.product) == D("12.000")
    assert (
        client.get(f"{ORDERS}/{order['id']}", headers=a.headers).json()["lines"][0]["quantity_open"]
        == "0.000"
    )
    assert find_mismatches(db, a.tenant.id) == []


def test_two_receipt_lines_for_one_order_line_add_up_against_the_open_quantity(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "10"))
    refused = receive(client, a, order, (0, "6"), (0, "6"))
    assert refused.status_code == 409
    assert receive(client, a, order, (0, "6"), (0, "4")).status_code == 201


def test_price_variance_is_flagged_above_ten_percent_only(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "30"))
    line_id = order["lines"][0]["id"]

    def cost(value: str) -> Any:
        return receive(
            client, a, order, {"po_line_id": line_id, "quantity_received": "5", "unit_cost": value}
        )

    assert [
        w["code"] for w in cost("8.8000").json()["warnings"] if w["code"] == "PRICE_VARIANCE"
    ] == []
    flagged = cost("9.2000").json()["warnings"]
    variance = next(w for w in flagged if w["code"] == "PRICE_VARIANCE")
    assert "15 percent more" in variance["message"]
    assert variance["line_index"] == 0
    cheaper = cost("6.0000").json()["warnings"]
    assert "25 percent less" in next(w for w in cheaper if w["code"] == "PRICE_VARIANCE")["message"]


def test_invoice_total_that_does_not_match_the_lines_is_flagged(
    client: TestClient, shop: TwoTenants
) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "30"))
    ok = receive(client, a, order, (0, "10"), invoice_total="80.50")
    assert "INVOICE_TOTAL_DIFFERS" not in [w["code"] for w in ok.json()["warnings"]]
    off = receive(client, a, order, (0, "10"), invoice_total="95.00")
    assert "INVOICE_TOTAL_DIFFERS" in [w["code"] for w in off.json()["warnings"]]


def test_receipt_rules_about_state_dates_and_lines(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    draft = new_order(client, a, (a.product, "10"))
    assert receive(client, a, draft, (0, "1")).status_code == 409  # not sent yet
    order = sent_order(client, a, (a.product, "10"))
    line_id = order["lines"][0]["id"]
    tomorrow = (today_ist() + timedelta(days=1)).isoformat()
    assert receive(client, a, order, (0, "1"), received_on=tomorrow).status_code == 422
    assert receive(client, a, order, (0, "1"), received_on="2020-01-01").status_code == 422
    assert (
        receive(
            client,
            a,
            order,
            {"po_line_id": str(uuid.uuid4()), "quantity_received": "1", "unit_cost": "8"},
        ).status_code
        == 404
    )
    other_order = sent_order(client, a, (a.product, "5"))
    assert (
        receive(
            client,
            a,
            order,
            {
                "po_line_id": other_order["lines"][0]["id"],
                "quantity_received": "1",
                "unit_cost": "8",
            },
        ).status_code
        == 404
    )
    bad = {"po_line_id": line_id, "quantity_received": "0", "unit_cost": "8"}
    assert receive(client, a, order, bad).status_code == 422
    assert receive(client, a, order, {**bad, "quantity_received": 1.5}).status_code == 422
    assert (
        client.post(
            f"{ORDERS}/{order['id']}/receipts", headers=a.headers, json={"lines": []}
        ).status_code
        == 422
    )
    assert on_hand(db, a.product) == D(0)
    plain_batch = {
        "po_line_id": line_id,
        "quantity_received": "1",
        "unit_cost": "8",
        "batch_no": "X1",
    }
    assert receive(client, a, order, plain_batch).status_code == 422  # not tracked by batch
    assert find_mismatches(db, a.tenant.id) == []
    assert client.get(f"{ORDERS}/{order['id']}", headers=b.headers).status_code == 404


# --------------------------------------------------------------------------- batches


@pytest.fixture
def medical(db: Session, two_tenants: TwoTenants) -> tuple[Any, Any, dict[str, Any]]:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category, name="Paracetamol 500 mg")
    factories.make_terms(
        db, a.tenant, a.supplier, product, purchase_price=D("20.0000"), pack_size=D(10)
    )
    return a, product, {}


def batch_line(order: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "po_line_id": order["lines"][0]["id"],
        "quantity_received": "10",
        "unit_cost": "20.0000",
        "batch_no": "K3A17",
        "expiry_date": (today_ist() + timedelta(days=400)).isoformat(),
        "mrp": "35.00",
        **fields,
    }


def test_receiving_a_batch_tracked_product_creates_the_batch(
    client: TestClient, db: Session, medical: tuple[Any, Any, Any]
) -> None:
    a, product, _ = medical
    order = sent_order(client, a, (product, "20"))
    response = receive(
        client,
        a,
        order,
        batch_line(order, manufactured_on=(today_ist() - timedelta(days=60)).isoformat()),
    )
    assert response.status_code == 201, response.text
    (line,) = response.json()["lines"]
    assert (line["batch_no"], line["mrp"], line["quantity_received"]) == (
        "K3A17",
        "35.00",
        "10.000",
    )
    batch = db.execute(
        select(ProductBatch).where(ProductBatch.product_id == product.id)
    ).scalar_one()
    assert (batch.batch_no, batch.initial_qty, batch.unit_cost, batch.status) == (
        "K3A17",
        D("10.000"),
        D("20.0000"),
        "active",
    )
    assert batch.received_on == today_ist()
    assert on_hand(db, product, batch) == D("10.000")
    assert find_mismatches(db, a.tenant.id) == []

    again = receive(client, a, order, batch_line(order, quantity_received="10"))
    assert again.status_code == 201
    batches = (
        db.execute(select(ProductBatch).where(ProductBatch.product_id == product.id))
        .scalars()
        .all()
    )
    assert len(batches) == 1  # the same batch number adds to the same batch
    assert batches[0].initial_qty == D("20.000")
    assert on_hand(db, product, batches[0]) == D("20.000")


@pytest.mark.parametrize("missing", ["batch_no", "expiry_date", "mrp"])
def test_batch_details_are_required_for_tracked_products(
    client: TestClient, medical: tuple[Any, Any, Any], missing: str
) -> None:
    a, product, _ = medical
    order = sent_order(client, a, (product, "20"))
    line = batch_line(order)
    del line[missing]
    response = receive(client, a, order, line)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == f"lines[0].{missing}"


def test_batch_date_and_conflict_rules(
    client: TestClient, db: Session, medical: tuple[Any, Any, Any]
) -> None:
    a, product, _ = medical
    order = sent_order(client, a, (product, "50"))
    today = today_ist()
    expired = receive(client, a, order, batch_line(order, expiry_date=today.isoformat()))
    assert expired.status_code == 422
    assert "expired" in expired.json()["error"]["message"]
    future_made = receive(
        client, a, order, batch_line(order, manufactured_on=(today + timedelta(days=1)).isoformat())
    )
    assert future_made.status_code == 422
    assert receive(client, a, order, batch_line(order, batch_no="has space")).status_code == 422
    assert receive(client, a, order, batch_line(order)).status_code == 201
    other_expiry = receive(
        client, a, order, batch_line(order, expiry_date=(today + timedelta(days=500)).isoformat())
    )
    assert other_expiry.status_code == 409
    batch = db.execute(
        select(ProductBatch).where(ProductBatch.product_id == product.id)
    ).scalar_one()
    batch.status = "quarantined"
    db.flush()
    assert receive(client, a, order, batch_line(order)).status_code == 409
    assert find_mismatches(db, a.tenant.id) == []


# --------------------------------------------------------------------------- receipts without an order


def direct_payload(bundle: Any, product: Any, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "supplier_id": str(bundle.supplier.id),
        "is_exception": True,
        "exception_note": "Walk in delivery, no order",
        "lines": [{"product_id": str(product.id), "quantity_received": "6", "unit_cost": "7.0000"}],
    }
    body.update(changes)
    return body


def test_a_receipt_without_an_order_must_be_an_exception_with_a_note(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    good = client.post(RECEIPTS, headers=a.headers, json=direct_payload(a, a.product))
    assert good.status_code == 201, good.text
    body = good.json()
    assert (body["purchase_order_id"], body["po_number"], body["is_exception"]) == (
        None,
        None,
        True,
    )
    assert body["exception_note"] == "Walk in delivery, no order"
    assert on_hand(db, a.product) == D("6.000")
    assert find_mismatches(db, a.tenant.id) == []
    assert (
        client.post(
            RECEIPTS, headers=a.headers, json=direct_payload(a, a.product, is_exception=False)
        ).status_code
        == 422
    )
    no_note = direct_payload(a, a.product)
    del no_note["exception_note"]
    assert client.post(RECEIPTS, headers=a.headers, json=no_note).status_code == 422
    foreign = client.post(RECEIPTS, headers=a.headers, json=direct_payload(a, shop.b.product))
    assert foreign.status_code == 404
    other_supplier = client.post(
        RECEIPTS,
        headers=a.headers,
        json=direct_payload(a, a.product, supplier_id=str(shop.b.supplier.id)),
    )
    assert other_supplier.status_code == 404


def test_receipts_can_be_listed_and_read(client: TestClient, shop: TwoTenants) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "10"))
    first = receive(client, a, order, (0, "10"), invoice_no="INV-9").json()
    second = client.post(RECEIPTS, headers=a.headers, json=direct_payload(a, a.product)).json()
    listed = client.get(RECEIPTS, headers=a.headers).json()
    assert listed["total"] == 2
    assert {item["receipt_no"] for item in listed["items"]} == {
        first["receipt_no"],
        second["receipt_no"],
    }
    assert client.get(RECEIPTS, headers=a.headers, params={"q": "inv-9"}).json()["total"] == 1
    assert (
        client.get(RECEIPTS, headers=a.headers, params={"supplier_id": str(uuid.uuid4())}).json()[
            "total"
        ]
        == 0
    )
    detail = client.get(f"{RECEIPTS}/{first['id']}", headers=a.headers).json()
    assert detail["invoice_no"] == "INV-9"
    assert detail["lines"][0]["product_sku"] == a.product.sku


def test_receipts_are_idempotent(client: TestClient, db: Session, shop: TwoTenants) -> None:
    a = shop.a
    order = sent_order(client, a, (a.product, "20"))
    key = {"Idempotency-Key": "receipt-key-01"}
    first = receive(client, a, order, (0, "10"), headers=key)
    replay = receive(client, a, order, (0, "10"), headers=key)
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json() == first.json()
    assert on_hand(db, a.product) == D("10.000")
    assert movement_count(db, a.tenant, "receipt") == 1
    different = receive(client, a, order, (0, "5"), headers=key)
    assert different.status_code == 422
    assert different.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    direct_key = {"Idempotency-Key": "direct-key-001"}
    one = client.post(
        RECEIPTS, headers={**a.headers, **direct_key}, json=direct_payload(a, a.product)
    )
    two = client.post(
        RECEIPTS, headers={**a.headers, **direct_key}, json=direct_payload(a, a.product)
    )
    assert two.headers["idempotent-replay"] == "true"
    assert two.json() == one.json()
    assert on_hand(db, a.product) == D("16.000")


# --------------------------------------------------------------------------- overdue and lists


def test_overdue_orders_are_flagged_and_filterable(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a = shop.a
    late = sent_order(client, a, (a.product, "10"))
    on_time = sent_order(client, a, (a.product, "10"))
    draft = new_order(client, a, (a.product, "10"))
    partly = sent_order(client, a, (a.product, "10"))
    for order, days in ((late, 6), (draft, 6), (partly, 2)):
        row = db.get(PurchaseOrder, uuid.UUID(order["id"]))
        assert row is not None
        row.expected_date = today_ist() - timedelta(days=days)
    db.flush()
    receive(client, a, partly, (0, "4"))

    detail = client.get(f"{ORDERS}/{late['id']}", headers=a.headers).json()
    assert (detail["is_overdue"], detail["days_late"]) == (True, 6)
    assert client.get(f"{ORDERS}/{draft['id']}", headers=a.headers).json()["is_overdue"] is False

    def ids(**params: Any) -> set[str]:
        body = client.get(ORDERS, headers=a.headers, params=params).json()
        return {item["id"] for item in body["items"]}

    assert ids(overdue="true") == {late["id"], partly["id"]}
    assert ids(overdue="false") == {on_time["id"], draft["id"]}
    assert ids(status="draft") == {draft["id"]}
    assert ids(status="partially_received") == {partly["id"]}
    assert ids(supplier_id=str(a.supplier.id)) == {
        late["id"],
        on_time["id"],
        draft["id"],
        partly["id"],
    }
    assert ids(q=late["po_number"].lower()) == {late["id"]}
    item = next(
        i for i in client.get(ORDERS, headers=a.headers).json()["items"] if i["id"] == partly["id"]
    )
    assert (item["lines"], item["value"], item["received_value"], item["days_late"]) == (
        1,
        "80.00",
        "32.00",
        2,
    )
    assert client.get(ORDERS, headers=a.headers, params={"sort": "nope"}).status_code == 422


# --------------------------------------------------------------------------- 401 and isolation


ANY = uuid.uuid4()
ALL_ROUTES = [
    ("GET", "/purchase-orders", None),
    ("POST", "/purchase-orders", {}),
    ("GET", f"/purchase-orders/{ANY}", None),
    ("PATCH", f"/purchase-orders/{ANY}", {}),
    ("POST", f"/purchase-orders/{ANY}/send", None),
    ("POST", f"/purchase-orders/{ANY}/cancel", None),
    ("POST", f"/purchase-orders/{ANY}/close", None),
    ("POST", f"/purchase-orders/{ANY}/receipts", {}),
    ("POST", "/receipts", {}),
    ("GET", "/receipts", None),
    ("GET", f"/receipts/{ANY}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ALL_ROUTES)
def test_every_purchasing_route_needs_a_token(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert client.request(method, f"{API}{path}", json=body).status_code == 401


def test_tenant_b_cannot_see_or_change_tenant_a_orders_and_receipts(
    client: TestClient, db: Session, shop: TwoTenants
) -> None:
    a, b = shop.a, shop.b
    order = sent_order(client, a, (a.product, "10"))
    receipt = receive(client, a, order, (0, "4")).json()
    line = [{"po_line_id": order["lines"][0]["id"], "quantity_received": "1", "unit_cost": "8"}]
    attacks = [
        ("GET", f"/purchase-orders/{order['id']}", None),
        ("PATCH", f"/purchase-orders/{order['id']}", {"notes": "Hacked"}),
        ("POST", f"/purchase-orders/{order['id']}/send", None),
        ("POST", f"/purchase-orders/{order['id']}/cancel", None),
        ("POST", f"/purchase-orders/{order['id']}/close", None),
        ("POST", f"/purchase-orders/{order['id']}/receipts", {"lines": line}),
        ("GET", f"/receipts/{receipt['id']}", None),
    ]
    for method, path, body in attacks:
        response = client.request(method, f"{API}{path}", headers=b.headers, json=body)
        assert response.status_code == 404, (method, path, response.text)
    assert client.get(ORDERS, headers=b.headers).json()["items"] == []
    assert client.get(RECEIPTS, headers=b.headers).json()["items"] == []
    untouched = client.get(f"{ORDERS}/{order['id']}", headers=a.headers).json()
    assert untouched["status"] == "partially_received"
    assert untouched["notes"] is None
    assert on_hand(db, b.product) == D(0)
