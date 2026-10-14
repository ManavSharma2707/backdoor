"""Stock levels, batches, movements, adjustments, write offs, counts, stockouts, reconcile."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_ist
from app.models.inventory import (
    InventoryMovement,
    StockAdjustment,
    StockBalance,
    StockoutInterval,
)
from app.models.ops import AuditLog
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
    tracked_product,
)
from tests.conftest import TwoTenants

D = Decimal
INV = f"{API}/inventory"


def ids(response: Any, key: str = "product_id") -> list[str]:
    assert response.status_code == 200, response.text
    return [item[key] for item in response.json()["items"]]


# --------------------------------------------------------------------------- stock levels


def test_stock_levels_show_quantities_value_and_status(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    low = factories.make_product(
        db, a.tenant, category=a.category, name="Low", min_stock_qty=D("5")
    )
    out = factories.make_product(db, a.tenant, category=a.category, name="Out")
    stock_up(db, a.tenant, a.user, a.product, "20", cost="6.0000")
    stock_up(db, a.tenant, a.user, low, "3", cost="2.0000")
    body = client.get(f"{INV}/stock", headers=a.headers, params={"sort": "name:asc"}).json()
    rows = {r["name"]: r for r in body["items"]}
    assert rows[a.product.name]["on_hand"] == "20.000"
    assert rows[a.product.name]["value"] == "120.00"
    assert rows[a.product.name]["status"] == "ok"
    assert rows["Low"]["status"] == "low"
    assert rows["Out"]["status"] == "out"
    assert rows["Out"]["product_id"] == str(out.id)
    assert rows[a.product.name]["risk_level"] is None
    assert rows[a.product.name]["last_count_date"] is None

    def with_status(value: str) -> set[str]:
        got = client.get(f"{INV}/stock", headers=a.headers, params={"status": value})
        return {r["name"] for r in got.json()["items"]}

    assert with_status("out") == {"Out"}
    assert with_status("low") == {"Low"}
    assert with_status("ok") == {a.product.name}


def test_stock_levels_separate_sellable_incoming_and_overdue(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category, name="Tracked")
    make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=60, quantity="6")
    make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=-3, quantity="4")
    make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=90, quantity="2", status="quarantined"
    )
    for status, days, qty in (
        ("sent", 2, 10),
        ("sent", -4, 7),
        ("draft", 2, 50),
        ("cancelled", 2, 60),
    ):
        po = factories.make_po(
            db,
            a.tenant,
            a.supplier,
            status=status,
            expected_date=today_ist() + timedelta(days=days),
        )
        factories.make_po_line(
            db, a.tenant, po, product, quantity_ordered=D(qty), quantity_received=D(0)
        )
    db.flush()
    row = next(
        r
        for r in client.get(f"{INV}/stock", headers=a.headers).json()["items"]
        if r["name"] == "Tracked"
    )
    assert row["on_hand"] == "12.000"
    assert row["sellable"] == "6.000"  # expired and held stock is not sellable
    assert row["incoming"] == "10.000"
    assert row["incoming_overdue"] == "7.000"
    assert row["status"] == "expired"
    assert (
        client.get(f"{INV}/stock", headers=a.headers, params={"status": "expired"}).json()["total"]
        == 1
    )


def test_stock_levels_filters_search_risk_and_last_count(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    other_category = factories.make_category(db, a.tenant)
    tea = factories.make_product(db, a.tenant, category=other_category, name="Tea", sku="TEA-1")
    run = factories.make_recommendation_run(db, a.tenant)
    factories.make_recommendation_line(db, a.tenant, run, tea, risk_level="critical")
    factories.make_recommendation_line(db, a.tenant, run, a.product, risk_level="low")
    older = factories.make_recommendation_run(
        db, a.tenant, as_of_date=today_ist() - timedelta(days=30)
    )
    factories.make_recommendation_line(db, a.tenant, older, tea, risk_level="none")
    db.flush()

    def search(**params: Any) -> list[str]:
        return ids(client.get(f"{INV}/stock", headers=a.headers, params=params))

    assert search(q="tea") == [str(tea.id)]
    assert search(category_id=str(other_category.id)) == [str(tea.id)]
    assert search(risk="critical") == [str(tea.id)]  # the latest plan decides
    assert search(risk="low") == [str(a.product.id)]
    assert search(risk="none") == []
    assert (
        client.get(f"{INV}/stock", headers=a.headers, params={"risk": "extreme"}).status_code == 422
    )
    assert (
        client.get(f"{INV}/stock", headers=a.headers, params={"sort": "bogus"}).status_code == 422
    )

    stock_up(db, a.tenant, a.user, tea, "5")
    count = client.post(
        f"{INV}/counts", headers=a.headers, json={"scope": "products", "product_ids": [str(tea.id)]}
    ).json()
    client.patch(
        f"{INV}/counts/{count['id']}/lines",
        headers=a.headers,
        json={"lines": [{"line_id": count["lines"][0]["id"], "counted_qty": "5"}]},
    )
    client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers)
    row = next(
        r
        for r in client.get(f"{INV}/stock", headers=a.headers).json()["items"]
        if r["sku"] == "TEA-1"
    )
    assert row["last_count_date"] == today_ist().isoformat()
    assert row["risk_level"] == "critical"

    a.product.is_active = False
    db.flush()
    assert str(a.product.id) not in search()
    assert str(a.product.id) in search(include_inactive="true")


# --------------------------------------------------------------------------- batches


def test_batches_list_earliest_expiry_first_with_days_and_sell_first(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    gone = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=-10, quantity="3", batch_no="GONE"
    )
    soon = make_batch_with_stock(
        db,
        a.tenant,
        a.user,
        product,
        days_to_expiry=15,
        quantity="4",
        batch_no="SOON",
        cost="2.5000",
    )
    late = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=200, quantity="9", batch_no="LATE"
    )
    empty = factories.make_batch(
        db, a.tenant, product, batch_no="EMPTY", expiry_date=today_ist() + timedelta(days=5)
    )
    body = client.get(f"{INV}/batches", headers=a.headers).json()
    assert [b["batch_no"] for b in body["items"]] == ["GONE", "SOON", "LATE"]
    by_no = {b["batch_no"]: b for b in body["items"]}
    assert by_no["GONE"]["days_to_expiry"] == -10
    assert by_no["GONE"]["is_expired"] is True
    assert by_no["SOON"]["days_to_expiry"] == 15
    assert (by_no["SOON"]["value"], by_no["SOON"]["unit_cost"], by_no["SOON"]["on_hand"]) == (
        "10.00",
        "2.5000",
        "4.000",
    )
    assert {no: b["sell_first"] for no, b in by_no.items()} == {
        "GONE": False,
        "SOON": True,
        "LATE": False,
    }

    def batch_ids(**params: Any) -> list[str]:
        return ids(client.get(f"{INV}/batches", headers=a.headers, params=params), "batch_id")

    assert batch_ids(expiring_within_days=30) == [str(gone.id), str(soon.id)]
    assert batch_ids(expired="true") == [str(gone.id)]
    assert batch_ids(expired="false") == [str(soon.id), str(late.id)]
    assert str(empty.id) in batch_ids(include_empty="true")
    assert batch_ids(product_id=str(uuid.uuid4())) == []
    assert batch_ids(status="closed") == []
    assert (
        client.get(
            f"{INV}/batches", headers=a.headers, params={"expiring_within_days": -1}
        ).status_code
        == 422
    )


def test_product_stock_lists_batches_and_totals(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=-1, quantity="2")
    make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=50, quantity="5", cost="4.0000"
    )
    body = client.get(f"{API}/products/{product.id}/stock", headers=a.headers).json()
    assert (body["on_hand"], body["sellable"], body["value"]) == ("7.000", "5.000", "30.00")
    assert len(body["batches"]) == 2
    assert client.get(f"{API}/products/{uuid.uuid4()}/stock", headers=a.headers).status_code == 404


# --------------------------------------------------------------------------- movements


def test_movements_are_listed_newest_first_and_filtered(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    post_sale(client, a.headers, sale_payload(line(a.product, "3")))
    client.post(
        f"{INV}/adjustments",
        headers=a.headers,
        json={
            "product_id": str(a.product.id),
            "quantity_delta": "-1",
            "reason_code": "damage",
            "note": "Dropped",
        },
    )
    body = client.get(f"{INV}/movements", headers=a.headers).json()
    assert [m["movement_type"] for m in body["items"]] == ["damage", "sale", "receipt"]
    first = body["items"][0]
    assert (first["quantity_delta"], first["reason_code"], first["note"]) == (
        "-1.000",
        "damage",
        "Dropped",
    )
    assert first["created_by_name"] == "Test Owner"
    assert first["sku"] == a.product.sku
    only_sales = client.get(f"{INV}/movements", headers=a.headers, params={"type": "sale"}).json()
    assert [m["quantity_delta"] for m in only_sales["items"]] == ["-3.000"]
    today = today_ist().isoformat()
    assert (
        client.get(
            f"{INV}/movements", headers=a.headers, params={"from": today, "to": today}
        ).json()["total"]
        == 3
    )
    assert (
        client.get(f"{INV}/movements", headers=a.headers, params={"to": "2020-01-01"}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(f"{INV}/movements", headers=a.headers, params={"type": "teleport"}).status_code
        == 422
    )
    assert (
        client.get(
            f"{INV}/movements", headers=a.headers, params={"product_id": str(uuid.uuid4())}
        ).json()["total"]
        == 0
    )


# --------------------------------------------------------------------------- adjustments


def adjust(
    client: TestClient, headers: dict[str, str], product: Any, delta: str, reason: str, **extra: Any
) -> Any:
    return client.post(
        f"{INV}/adjustments",
        headers=headers,
        json={
            "product_id": str(product.id),
            "quantity_delta": delta,
            "reason_code": reason,
            **extra,
        },
    )


def test_adjustments_move_stock_and_record_both_rows(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    removed = adjust(client, a.headers, a.product, "-4", "theft_loss", note="Missing after closing")
    assert removed.status_code == 201, removed.text
    body = removed.json()
    assert (body["quantity_delta"], body["on_hand_after"], body["reason_code"]) == (
        "-4.000",
        "6.000",
        "theft_loss",
    )
    added = adjust(client, a.headers, a.product, "2.5", "found")
    assert added.json()["on_hand_after"] == "8.500"
    assert on_hand(db, a.product) == D("8.500")
    rows = db.execute(select(StockAdjustment).order_by(StockAdjustment.created_at)).scalars().all()
    assert len(rows) == 2
    movement = db.get(InventoryMovement, rows[0].movement_id)
    assert movement is not None
    assert (movement.movement_type, movement.source_type, movement.source_id) == (
        "adjustment",
        "adjustment",
        str(rows[0].id),
    )
    assert (
        db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "adjustment.create")
        ).scalar_one()
        == 2
    )
    assert find_mismatches(db, a.tenant.id) == []


@pytest.mark.parametrize(
    ("reason", "movement_type"),
    [
        ("damage", "damage"),
        ("expiry_writeoff", "expiry_writeoff"),
        ("supplier_return", "supplier_return"),
        ("theft_loss", "adjustment"),
        ("correction", "adjustment"),
        ("other", "adjustment"),
    ],
)
def test_reason_decides_the_movement_type(
    client: TestClient, db: Session, two_tenants: TwoTenants, reason: str, movement_type: str
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    response = adjust(client, a.headers, a.product, "-1", reason, note="Reason given")
    assert response.status_code == 201
    assert (
        db.execute(
            select(InventoryMovement.movement_type).order_by(InventoryMovement.id.desc()).limit(1)
        ).scalar_one()
        == movement_type
    )


@pytest.mark.parametrize(
    ("delta", "reason", "extra"),
    [
        ("0", "correction", {}),
        ("3", "damage", {}),
        ("3", "theft_loss", {}),
        ("-3", "found", {}),
        ("-3", "other", {}),
        ("1.0005", "correction", {}),
        (1.5, "correction", {}),
        ("-1", "mystery", {}),
        ("-1", "correction", {"note": ""}),
    ],
)
def test_adjustment_validation(
    client: TestClient,
    db: Session,
    two_tenants: TwoTenants,
    delta: Any,
    reason: str,
    extra: dict[str, Any],
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    assert adjust(client, a.headers, a.product, delta, reason, **extra).status_code == 422
    assert on_hand(db, a.product) == D("10.000")


def test_removing_more_than_is_there_is_a_409_and_changes_nothing(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "2")
    refused = adjust(client, a.headers, a.product, "-3", "correction")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert "2 on hand, 3 needed" in refused.json()["error"]["message"]
    assert on_hand(db, a.product) == D("2.000")
    assert db.execute(select(func.count()).select_from(StockAdjustment)).scalar_one() == 0


def test_batch_rules_for_adjustments(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    product = tracked_product(db, a.tenant, category=a.category)
    batch = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=60, quantity="5")
    other = make_batch_with_stock(
        db,
        a.tenant,
        a.user,
        tracked_product(db, a.tenant, category=a.category),
        days_to_expiry=60,
        quantity="5",
    )
    foreign_product = tracked_product(db, b.tenant, category=b.category)
    foreign = make_batch_with_stock(
        db, b.tenant, b.user, foreign_product, days_to_expiry=60, quantity="5"
    )

    assert adjust(client, a.headers, product, "-1", "damage").status_code == 422  # batch required
    ok = adjust(client, a.headers, product, "-2", "damage", batch_id=str(batch.id))
    assert ok.status_code == 201
    assert (ok.json()["batch_no"], ok.json()["on_hand_after"]) == (batch.batch_no, "3.000")
    assert (
        adjust(client, a.headers, product, "-1", "damage", batch_id=str(other.id)).status_code
        == 404
    )
    assert (
        adjust(client, a.headers, product, "-1", "damage", batch_id=str(foreign.id)).status_code
        == 404
    )
    plain = two_tenants.a.product
    stock_up(db, a.tenant, a.user, plain, "5")
    assert (
        adjust(client, a.headers, plain, "-1", "damage", batch_id=str(batch.id)).status_code == 422
    )
    assert (
        adjust(
            client, a.headers, foreign_product, "-1", "damage", batch_id=str(foreign.id)
        ).status_code
        == 404
    )
    assert find_mismatches(db, a.tenant.id) == []


def test_adjustments_are_idempotent(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    headers = {**a.headers, "Idempotency-Key": "adjust-key-001"}
    body = {"product_id": str(a.product.id), "quantity_delta": "-2", "reason_code": "damage"}
    first = client.post(f"{INV}/adjustments", headers=headers, json=body)
    replay = client.post(f"{INV}/adjustments", headers=headers, json=body)
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json() == first.json()
    assert on_hand(db, a.product) == D("8.000")
    clash = client.post(
        f"{INV}/adjustments", headers=headers, json={**body, "quantity_delta": "-3"}
    )
    assert clash.status_code == 422
    assert clash.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"


# --------------------------------------------------------------------------- write off


def test_an_expired_batch_is_written_off_in_full_and_closed(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    expired = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=-2, quantity="6", cost="5.0000"
    )
    response = client.post(
        f"{INV}/batches/{expired.id}/write-off", headers=a.headers, json={"reason": "expired"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["quantity_delta"], body["reason_code"], body["on_hand_after"]) == (
        "-6.000",
        "expiry_writeoff",
        "0.000",
    )
    assert on_hand(db, product, expired) == D(0)
    db.refresh(expired)
    assert expired.status == "closed"
    assert (
        db.execute(
            select(InventoryMovement.movement_type).order_by(InventoryMovement.id.desc()).limit(1)
        ).scalar_one()
        == "expiry_writeoff"
    )
    audit = db.execute(select(AuditLog).where(AuditLog.action == "batch.write_off")).scalar_one()
    assert audit.after["value"] == "30.00"
    again = client.post(
        f"{INV}/batches/{expired.id}/write-off", headers=a.headers, json={"reason": "expired"}
    )
    assert again.status_code == 409
    assert find_mismatches(db, a.tenant.id) == []


def test_write_off_rules(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a, two_tenants.b
    product = tracked_product(db, a.tenant, category=a.category)
    fresh = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=100, quantity="4")
    url = f"{INV}/batches/{fresh.id}/write-off"
    refused = client.post(url, headers=a.headers, json={"reason": "expired"})
    assert refused.status_code == 409
    assert "not expired yet" in refused.json()["error"]["message"]
    assert client.post(url, headers=a.headers, json={"reason": "stolen"}).status_code == 422
    damaged = client.post(
        url, headers=a.headers, json={"reason": "damaged", "note": "Water damage"}
    )
    assert damaged.status_code == 201
    assert damaged.json()["reason_code"] == "damage"
    foreign = make_batch_with_stock(
        db,
        b.tenant,
        b.user,
        tracked_product(db, b.tenant, category=b.category),
        days_to_expiry=-1,
        quantity="2",
    )
    assert (
        client.post(
            f"{INV}/batches/{foreign.id}/write-off", headers=a.headers, json={"reason": "expired"}
        ).status_code
        == 404
    )
    assert on_hand(
        db, foreign.product_id and db.get(type(product), foreign.product_id), foreign
    ) == D("2.000")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- supplier returns


def return_body(product: Any, quantity: str = "2", **extra: Any) -> dict[str, Any]:
    return {
        "note": "Near expiry stock",
        "lines": [{"product_id": str(product.id), "quantity": quantity, **extra}],
    }


def test_stock_goes_back_to_a_supplier_that_takes_returns(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    a.supplier.accepts_expiry_returns = True
    a.supplier.expiry_return_window_days = 60
    product = tracked_product(db, a.tenant, category=a.category)
    near = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=20, quantity="8")
    response = client.post(
        f"{API}/suppliers/{a.supplier.id}/returns",
        headers=a.headers,
        json={**return_body(product, "3", batch_id=str(near.id)), "credit_note_no": "CN-5"},
    )
    assert response.status_code == 201, response.text
    (adjustment,) = response.json()["adjustments"]
    assert (
        adjustment["quantity_delta"],
        adjustment["reason_code"],
        adjustment["on_hand_after"],
    ) == ("-3.000", "supplier_return", "5.000")
    assert "CN-5" in adjustment["note"]
    assert (
        db.execute(
            select(InventoryMovement.movement_type).order_by(InventoryMovement.id.desc()).limit(1)
        ).scalar_one()
        == "supplier_return"
    )
    assert find_mismatches(db, a.tenant.id) == []


def test_supplier_return_policy(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    expired = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=-5, quantity="4")
    url = f"{API}/suppliers/{a.supplier.id}/returns"
    body = return_body(product, "1", batch_id=str(expired.id))
    refused = client.post(url, headers=a.headers, json=body)
    assert refused.status_code == 409
    assert "does not take back expired stock" in refused.json()["error"]["message"]
    a.supplier.accepts_expiry_returns = True
    a.supplier.expiry_return_window_days = 3
    db.flush()
    too_late = client.post(url, headers=a.headers, json=body)
    assert too_late.status_code == 409
    assert "within 3 days" in too_late.json()["error"]["message"]
    a.supplier.expiry_return_window_days = 30
    db.flush()
    assert client.post(url, headers=a.headers, json=body).status_code == 201
    too_many = client.post(
        url, headers=a.headers, json=return_body(product, "99", batch_id=str(expired.id))
    )
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert (
        client.post(
            f"{API}/suppliers/{uuid.uuid4()}/returns", headers=a.headers, json=body
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- counts


def start_count(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    response = client.post(f"{INV}/counts", headers=headers, json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def enter(
    client: TestClient,
    headers: dict[str, str],
    count: dict[str, Any],
    values: dict[int, str | None],
) -> Any:
    lines = [{"line_id": count["lines"][i]["id"], "counted_qty": q} for i, q in values.items()]
    return client.patch(f"{INV}/counts/{count['id']}/lines", headers=headers, json={"lines": lines})


def test_count_snapshot_entry_and_posting(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    second = factories.make_product(db, a.tenant, category=a.category, name="Zeta")
    stock_up(db, a.tenant, a.user, a.product, "10", cost="4.0000")
    stock_up(db, a.tenant, a.user, second, "6", cost="2.0000")
    count = start_count(client, a.headers, note="Monthly")
    assert count["status"] == "draft"
    assert count["count_date"] == today_ist().isoformat()
    assert [
        (item["name"], item["system_qty"], item["counted_qty"], item["variance"])
        for item in count["lines"]
    ] == [(a.product.name, "10.000", None, None), ("Zeta", "6.000", None, None)]
    assert (count["counted_lines"], count["variance_lines"]) == (0, 0)

    entered = enter(client, a.headers, count, {0: "8", 1: "6"}).json()
    assert [item["variance"] for item in entered["lines"]] == ["-2.000", "0.000"]
    assert (entered["counted_lines"], entered["variance_lines"], entered["variance_value"]) == (
        2,
        1,
        "-8.00",
    )
    cleared = enter(client, a.headers, count, {1: None}).json()
    assert cleared["lines"][1]["counted_qty"] is None
    enter(client, a.headers, count, {1: "7"})

    posted = client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers)
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["status"] == "posted"
    assert body["posted_at"] is not None
    assert on_hand(db, a.product) == D("8.000")
    assert on_hand(db, second) == D("7.000")
    corrections = db.execute(
        select(InventoryMovement.quantity_delta, InventoryMovement.source_id).where(
            InventoryMovement.movement_type == "count_correction"
        )
    ).all()
    assert sorted(q for q, _ in corrections) == [D("-2.000"), D("1.000")]
    assert {s for _, s in corrections} == {count["id"]}
    assert (
        db.execute(select(AuditLog.after).where(AuditLog.action == "count.post")).scalar_one()[
            "lines_with_difference"
        ]
        == 2
    )
    assert find_mismatches(db, a.tenant.id) == []
    assert client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers).status_code == 409
    assert enter(client, a.headers, count, {0: "1"}).status_code == 409


def test_uncounted_lines_are_left_alone_and_an_empty_count_cannot_post(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    other = factories.make_product(db, a.tenant, category=a.category, name="Zeta")
    stock_up(db, a.tenant, a.user, a.product, "10")
    stock_up(db, a.tenant, a.user, other, "10")
    count = start_count(client, a.headers)
    assert client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers).status_code == 409
    enter(client, a.headers, count, {0: "9"})
    assert client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers).status_code == 200
    assert on_hand(db, other) == D("10.000")


def test_count_scopes(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a, two_tenants.b
    other_category = factories.make_category(db, a.tenant)
    tea = factories.make_product(db, a.tenant, category=other_category, name="Tea")
    stock_up(db, a.tenant, a.user, tea, "4")
    tracked = tracked_product(db, a.tenant, category=other_category, name="Pills")
    make_batch_with_stock(
        db, a.tenant, a.user, tracked, days_to_expiry=100, quantity="3", batch_no="P1"
    )
    make_batch_with_stock(
        db, a.tenant, a.user, tracked, days_to_expiry=50, quantity="5", batch_no="P2"
    )
    factories.make_batch(db, a.tenant, tracked, batch_no="EMPTY")
    by_category = start_count(
        client, a.headers, scope="category", category_id=str(other_category.id)
    )
    assert [(item["name"], item["batch_no"]) for item in by_category["lines"]] == [
        ("Pills", "P2"),
        ("Pills", "P1"),
        ("Tea", None),
    ]
    chosen = start_count(client, a.headers, scope="products", product_ids=[str(tea.id)])
    assert [item["name"] for item in chosen["lines"]] == ["Tea"]
    assert (
        client.post(f"{INV}/counts", headers=a.headers, json={"scope": "category"}).status_code
        == 422
    )
    assert (
        client.post(f"{INV}/counts", headers=a.headers, json={"scope": "products"}).status_code
        == 422
    )
    assert (
        client.post(
            f"{INV}/counts",
            headers=a.headers,
            json={"scope": "category", "category_id": str(b.category.id)},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{INV}/counts",
            headers=a.headers,
            json={"scope": "products", "product_ids": [str(b.product.id)]},
        ).status_code
        == 404
    )
    future = (today_ist() + timedelta(days=1)).isoformat()
    assert (
        client.post(f"{INV}/counts", headers=a.headers, json={"count_date": future}).status_code
        == 422
    )


def test_batch_counts_correct_each_batch(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    product = tracked_product(db, a.tenant, category=a.category)
    near = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=30, quantity="5", batch_no="N"
    )
    far = make_batch_with_stock(
        db, a.tenant, a.user, product, days_to_expiry=300, quantity="5", batch_no="F"
    )
    count = start_count(client, a.headers, scope="products", product_ids=[str(product.id)])
    enter(client, a.headers, count, {0: "4", 1: "7"})
    client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers)
    assert on_hand(db, product, near) == D("4.000")
    assert on_hand(db, product, far) == D("7.000")
    assert find_mismatches(db, a.tenant.id) == []


def test_a_difference_that_would_go_below_zero_is_refused(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    count = start_count(client, a.headers, scope="products", product_ids=[str(a.product.id)])
    post_sale(
        client, a.headers, sale_payload(line(a.product, "9"))
    )  # stock moves after the snapshot
    enter(client, a.headers, count, {0: "5"})  # a difference of minus 5 against 1 left
    refused = client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers)
    assert refused.status_code == 409
    assert "Stock changed since this count started" in refused.json()["error"]["message"]
    assert on_hand(db, a.product) == D("1.000")
    assert client.get(f"{INV}/counts/{count['id']}", headers=a.headers).json()["status"] == "draft"


def test_counts_can_be_listed_and_read(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "3")
    first = start_count(client, a.headers)
    second = start_count(client, a.headers)
    enter(client, a.headers, second, {0: "3"})
    client.post(f"{INV}/counts/{second['id']}/post", headers=a.headers)
    listed = client.get(f"{INV}/counts", headers=a.headers).json()
    assert listed["total"] == 2
    assert {c["id"]: (c["status"], c["lines"], c["counted_lines"]) for c in listed["items"]} == {
        first["id"]: ("draft", 1, 0),
        second["id"]: ("posted", 1, 1),
    }
    assert [
        c["id"]
        for c in client.get(f"{INV}/counts", headers=a.headers, params={"status": "draft"}).json()[
            "items"
        ]
    ] == [first["id"]]
    assert client.get(f"{INV}/counts/{uuid.uuid4()}", headers=a.headers).status_code == 404
    bad_line = client.patch(
        f"{INV}/counts/{first['id']}/lines",
        headers=a.headers,
        json={"lines": [{"line_id": str(uuid.uuid4()), "counted_qty": "1"}]},
    )
    assert bad_line.status_code == 404
    negative = client.patch(
        f"{INV}/counts/{first['id']}/lines",
        headers=a.headers,
        json={"lines": [{"line_id": first["lines"][0]["id"], "counted_qty": "-1"}]},
    )
    assert negative.status_code == 422


# --------------------------------------------------------------------------- stockouts


def test_stockout_periods(client: TestClient, db: Session, two_tenants: TwoTenants) -> None:
    a = two_tenants.a
    today = today_ist()
    url = f"{INV}/stockouts"
    created = client.post(
        url,
        headers=a.headers,
        json={
            "product_id": str(a.product.id),
            "start_date": (today - timedelta(days=10)).isoformat(),
            "end_date": (today - timedelta(days=7)).isoformat(),
            "note": "Supplier delay",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["days"], body["source"], body["sku"]) == (4, "recorded", a.product.sku)
    open_one = client.post(
        url,
        headers=a.headers,
        json={
            "product_id": str(a.product.id),
            "start_date": (today - timedelta(days=2)).isoformat(),
        },
    ).json()
    assert open_one["end_date"] is None
    assert open_one["days"] is None
    overlap = client.post(
        url,
        headers=a.headers,
        json={
            "product_id": str(a.product.id),
            "start_date": (today - timedelta(days=8)).isoformat(),
        },
    )
    assert overlap.status_code == 409
    closed = client.patch(
        f"{url}/{open_one['id']}",
        headers=a.headers,
        json={"end_date": (today - timedelta(days=1)).isoformat()},
    )
    assert closed.json()["days"] == 2
    assert client.get(url, headers=a.headers, params={"open_only": "true"}).json()["total"] == 0
    assert client.get(url, headers=a.headers).json()["total"] == 2
    assert (
        client.get(url, headers=a.headers, params={"product_id": str(uuid.uuid4())}).json()["total"]
        == 0
    )
    reopened = client.patch(
        f"{url}/{body['id']}",
        headers=a.headers,
        json={"end_date": (today - timedelta(days=2)).isoformat()},
    )
    assert reopened.status_code == 409  # now overlaps the second period
    assert (
        client.patch(f"{url}/{body['id']}", headers=a.headers, json={"note": "Edited"}).json()[
            "note"
        ]
        == "Edited"
    )


def test_stockout_validation_and_inferred_periods(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    today = today_ist()
    url = f"{INV}/stockouts"
    product = str(a.product.id)

    def post(**changes: Any) -> Any:
        return client.post(
            url,
            headers=a.headers,
            json={"product_id": product, "start_date": today.isoformat(), **changes},
        )

    assert post(start_date=(today + timedelta(days=1)).isoformat()).status_code == 422
    assert post(end_date=(today - timedelta(days=1)).isoformat()).status_code == 422
    assert post(end_date=(today + timedelta(days=1)).isoformat()).status_code == 422
    assert post(product_id=str(b.product.id)).status_code == 404
    inferred = StockoutInterval(
        tenant_id=a.tenant.id,
        product_id=a.product.id,
        start_date=today - timedelta(days=30),
        source="inferred",
    )
    db.add(inferred)
    db.flush()
    assert (
        client.patch(f"{url}/{inferred.id}", headers=a.headers, json={"note": "x"}).status_code
        == 409
    )
    assert (
        post(start_date=(today - timedelta(days=30)).isoformat()).status_code == 201
    )  # inferred does not block


# --------------------------------------------------------------------------- reconcile


def test_reconcile_reports_agreement_and_drift(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    stock_up(db, a.tenant, a.user, a.product, "10")
    clean = client.post(f"{INV}/reconcile", headers=a.headers)
    assert clean.status_code == 200
    assert clean.json()["ok"] is True
    assert clean.json()["mismatches"] == []
    balance = db.execute(
        select(StockBalance).where(StockBalance.product_id == a.product.id)
    ).scalar_one()
    balance.on_hand = D("12.000")
    db.flush()
    body = client.post(f"{INV}/reconcile", headers=a.headers).json()
    assert body["ok"] is False
    assert body["mismatches"][0]["code"] == "BATCH_QTY_MISMATCH"
    assert body["mismatches"][0]["detail"] == {"on_hand": "12.000", "ledger": "10.000"}
    assert client.post(f"{INV}/reconcile", headers=two_tenants.b.headers).json()["ok"] is True
    assert (
        db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "inventory.reconcile")
        ).scalar_one()
        == 3
    )


def test_a_full_day_of_trading_reconciles(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    """Receive, sell, return, void, adjust and count, then every check still agrees."""
    a = two_tenants.a
    factories.make_terms(db, a.tenant, a.supplier, a.product, is_primary=True)
    po = client.post(
        f"{API}/purchase-orders",
        headers=a.headers,
        json={
            "supplier_id": str(a.supplier.id),
            "lines": [{"product_id": str(a.product.id), "quantity_ordered": "40"}],
        },
    ).json()
    client.post(f"{API}/purchase-orders/{po['id']}/send", headers=a.headers)
    client.post(
        f"{API}/purchase-orders/{po['id']}/receipts",
        headers=a.headers,
        json={
            "lines": [
                {
                    "po_line_id": po["lines"][0]["id"],
                    "quantity_received": "40",
                    "unit_cost": "8.0000",
                }
            ]
        },
    )
    one = post_sale(client, a.headers, sale_payload(line(a.product, "5"))).json()
    two = post_sale(client, a.headers, sale_payload(line(a.product, "3"))).json()
    client.post(
        f"{API}/sales/{one['id']}/returns",
        headers=a.headers,
        json={
            "reason": "Customer returned",
            "lines": [
                {"sale_line_id": one["lines"][0]["id"], "quantity": "2", "disposition": "damaged"}
            ],
        },
    )
    client.post(f"{API}/sales/{two['id']}/void", headers=a.headers, json={"reason": "wrong item"})
    adjust(client, a.headers, a.product, "-1", "theft_loss")
    count = start_count(client, a.headers)
    enter(client, a.headers, count, {0: "30"})
    client.post(f"{INV}/counts/{count['id']}/post", headers=a.headers)
    assert on_hand(db, a.product) == D("30.000")
    assert client.post(f"{INV}/reconcile", headers=a.headers).json()["ok"] is True
    assert movement_count(db, a.tenant) >= 8


# --------------------------------------------------------------------------- 401 and isolation


ANY = uuid.uuid4()
ALL_ROUTES = [
    ("GET", "/inventory/stock", None),
    ("GET", "/inventory/batches", None),
    ("GET", "/inventory/movements", None),
    ("POST", "/inventory/adjustments", {}),
    ("POST", f"/inventory/batches/{ANY}/write-off", {}),
    ("POST", "/inventory/counts", {}),
    ("GET", "/inventory/counts", None),
    ("GET", f"/inventory/counts/{ANY}", None),
    ("PATCH", f"/inventory/counts/{ANY}/lines", {}),
    ("POST", f"/inventory/counts/{ANY}/post", None),
    ("GET", "/inventory/stockouts", None),
    ("POST", "/inventory/stockouts", {}),
    ("PATCH", f"/inventory/stockouts/{ANY}", {}),
    ("POST", "/inventory/reconcile", None),
    ("GET", f"/products/{ANY}/stock", None),
    ("POST", f"/suppliers/{ANY}/returns", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), ALL_ROUTES)
def test_every_inventory_route_needs_a_token(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert client.request(method, f"{API}{path}", json=body).status_code == 401


def test_tenant_b_cannot_read_or_change_tenant_a_stock(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    product = tracked_product(db, a.tenant, category=a.category)
    batch = make_batch_with_stock(db, a.tenant, a.user, product, days_to_expiry=-1, quantity="5")
    stock_up(db, a.tenant, a.user, a.product, "10")
    count = start_count(client, a.headers)
    interval = client.post(
        f"{INV}/stockouts",
        headers=a.headers,
        json={"product_id": str(a.product.id), "start_date": today_ist().isoformat()},
    ).json()

    attacks = [
        (
            "POST",
            "/inventory/adjustments",
            {"product_id": str(a.product.id), "quantity_delta": "-1", "reason_code": "damage"},
        ),
        ("POST", f"/inventory/batches/{batch.id}/write-off", {"reason": "expired"}),
        ("GET", f"/inventory/counts/{count['id']}", None),
        (
            "PATCH",
            f"/inventory/counts/{count['id']}/lines",
            {"lines": [{"line_id": count["lines"][0]["id"], "counted_qty": "0"}]},
        ),
        ("POST", f"/inventory/counts/{count['id']}/post", None),
        ("PATCH", f"/inventory/stockouts/{interval['id']}", {"note": "Hacked"}),
        ("GET", f"/products/{a.product.id}/stock", None),
        ("POST", f"/suppliers/{a.supplier.id}/returns", return_body(a.product)),
        (
            "POST",
            "/inventory/stockouts",
            {"product_id": str(a.product.id), "start_date": today_ist().isoformat()},
        ),
    ]
    for method, path, body in attacks:
        response = client.request(method, f"{API}{path}", headers=b.headers, json=body)
        assert response.status_code == 404, (method, path, response.status_code, response.text)

    for path in ("stock", "batches", "movements", "counts", "stockouts"):
        listed = client.get(f"{INV}/{path}", headers=b.headers).json()["items"]
        own = {str(b.product.id)} if path == "stock" else set()
        assert {row.get("product_id") for row in listed if row.get("product_id")} <= own, path
    assert on_hand(db, a.product) == D("10.000")
    assert on_hand(db, product, batch) == D("5.000")
    assert client.post(f"{INV}/reconcile", headers=b.headers).json()["mismatches"] == []
