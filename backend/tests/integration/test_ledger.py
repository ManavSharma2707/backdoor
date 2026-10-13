"""The ledger service against a real database: balances, cost, atomicity, reconciliation, locking."""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import transaction
from app.engine.ledger_rules import LedgerRuleError
from app.models.catalogue import Product
from app.models.inventory import InventoryMovement, StockBalance
from app.models.tenancy import Tenant
from app.services.ledger import InsufficientStockError, LedgerService, MovementEntry
from app.services.reconciliation import find_mismatches
from tests import factories

D = Decimal
WHEN = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)


def entry(
    product: Product,
    movement_type: str,
    delta: str,
    *,
    batch_id: uuid.UUID | None = None,
    cost: str | None = None,
    source: tuple[str, str] = ("adjustment", "t-1"),
) -> MovementEntry:
    return MovementEntry(
        product_id=product.id,
        batch_id=batch_id,
        movement_type=movement_type,
        quantity_delta=D(delta),
        source_type=source[0],
        source_id=source[1],
        unit_cost=D(cost) if cost is not None else None,
        occurred_at=WHEN,
    )


@pytest.fixture
def ledger(db: Session) -> tuple[LedgerService, Tenant, Product]:
    tenant = factories.make_tenant(db)
    user = factories.make_user(db, tenant)
    product = factories.make_product(db, tenant)
    return LedgerService(db, tenant.id, user.id), tenant, product


def balance_of(db: Session, product: Product, batch_id: uuid.UUID | None = None) -> StockBalance:
    return db.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.batch_id.is_(None)
            if batch_id is None
            else StockBalance.batch_id == batch_id,
        )
    ).scalar_one()


def test_receipt_creates_the_balance_row_and_the_movement(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    movements = service.post(
        [entry(product, "receipt", "12", cost="8.0000", source=("receipt", "r1"))]
    )
    assert len(movements) == 1
    move = movements[0]
    assert move.id is not None
    assert (move.quantity_delta, move.unit_cost, move.movement_type) == (
        D("12.000"),
        D("8.0000"),
        "receipt",
    )
    assert move.business_date.isoformat() == "2026-10-13"
    assert move.created_by == service.user_id
    row = balance_of(db, product)
    assert (row.on_hand, row.avg_unit_cost, row.last_movement_at) == (
        D("12.000"),
        D("8.0000"),
        WHEN,
    )
    assert find_mismatches(db, tenant.id) == []


def test_receipts_move_the_weighted_average_but_sales_do_not(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    service.post([entry(product, "receipt", "10", cost="8.0000")])
    service.post([entry(product, "receipt", "30", cost="9.0000")])
    assert balance_of(db, product).avg_unit_cost == D("8.7500")
    sold = service.post([entry(product, "sale", "-5")])[0]
    assert sold.unit_cost == D("8.7500")  # outflows are costed at the current average
    assert balance_of(db, product).avg_unit_cost == D("8.7500")
    service.post([entry(product, "return_in", "2", cost="1.0000")])  # returns keep the average
    assert balance_of(db, product).avg_unit_cost == D("8.7500")
    assert balance_of(db, product).on_hand == D("37.000")
    assert find_mismatches(db, tenant.id) == []


def test_each_batch_has_its_own_balance_and_cost(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    b1 = factories.make_batch(db, tenant, product, unit_cost=D("5.0000"))
    b2 = factories.make_batch(db, tenant, product, unit_cost=D("6.0000"))
    service.post(
        [
            entry(product, "receipt", "10", batch_id=b1.id, cost="5.0000"),
            entry(product, "receipt", "4", batch_id=b2.id, cost="6.0000"),
        ]
    )
    service.post([entry(product, "sale", "-3", batch_id=b1.id)])
    assert balance_of(db, product, b1.id).on_hand == D("7.000")
    assert balance_of(db, product, b2.id).avg_unit_cost == D("6.0000")
    assert service.on_hand(product.id, None) == D(0)  # no row for the "no batch" key
    assert find_mismatches(db, tenant.id) == []


def test_overdraw_raises_and_writes_nothing(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    other = factories.make_product(db, tenant)
    service.post(
        [entry(product, "receipt", "5", cost="1.0000"), entry(other, "receipt", "5", cost="1.0000")]
    )
    before = db.execute(select(func.count()).select_from(InventoryMovement)).scalar_one()
    with pytest.raises(InsufficientStockError) as caught:
        service.post(
            [entry(other, "sale", "-2"), entry(product, "sale", "-6"), entry(product, "sale", "-1")]
        )
    (short,) = caught.value.shortfalls
    assert (short.product_id, short.requested, short.available) == (
        product.id,
        D("7.000"),
        D("5.000"),
    )
    after = db.execute(select(func.count()).select_from(InventoryMovement)).scalar_one()
    assert after == before
    assert balance_of(db, other).on_hand == D("5.000")  # the valid first entry was not applied
    assert balance_of(db, product).on_hand == D("5.000")


def test_every_short_balance_is_reported_in_key_order(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    other = factories.make_product(db, tenant)
    with pytest.raises(InsufficientStockError) as caught:
        service.post([entry(product, "sale", "-1"), entry(other, "sale", "-2")])
    assert {s.product_id for s in caught.value.shortfalls} == {product.id, other.id}
    assert [str(s.product_id) for s in caught.value.shortfalls] == sorted(
        str(s.product_id) for s in caught.value.shortfalls
    )


def test_selling_from_a_product_that_was_never_stocked_is_short_not_a_crash(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, _, product = ledger
    with pytest.raises(InsufficientStockError) as caught:
        service.post([entry(product, "sale", "-1")])
    assert caught.value.shortfalls[0].available == D(0)


def test_a_return_and_its_write_off_can_post_together_from_zero(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    service.post([entry(product, "return_in", "2"), entry(product, "damage", "-2")])
    assert balance_of(db, product).on_hand == D(0)
    assert find_mismatches(db, tenant.id) == []


def test_rule_violations_are_refused_before_touching_the_database(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, _, product = ledger
    with pytest.raises(LedgerRuleError):
        service.post([entry(product, "sale", "1")])
    with pytest.raises(LedgerRuleError, match="3 decimal"):
        service.post([entry(product, "receipt", "1.0005")])
    assert service.post([]) == []
    assert db.execute(select(func.count()).select_from(InventoryMovement)).scalar_one() == 0


def test_movements_for_returns_one_documents_rows_in_order(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, _, product = ledger
    service.post([entry(product, "receipt", "9", cost="2.0000", source=("receipt", "r1"))])
    service.post(
        [
            entry(product, "sale", "-1", source=("sale", "s1")),
            entry(product, "sale", "-2", source=("sale", "s1")),
        ]
    )
    rows = service.movements_for("sale", "s1")
    assert [m.quantity_delta for m in rows] == [D("-1.000"), D("-2.000")]
    assert len(service.movements_for("sale", "s1", movement_type="receipt")) == 0
    assert len(service.movements_for("receipt", "r1")) == 1


def test_reconciliation_finds_a_balance_that_drifted_from_the_ledger(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    service, tenant, product = ledger
    service.post([entry(product, "receipt", "10", cost="1.0000")])
    assert find_mismatches(db, tenant.id) == []
    balance_of(db, product).on_hand = D("11.000")  # simulated corruption
    db.flush()
    (mismatch,) = find_mismatches(db, tenant.id)
    assert mismatch.code == "BATCH_QTY_MISMATCH"
    assert mismatch.detail == {"on_hand": "11.000", "ledger": "10.000"}


def test_reconciliation_finds_ledger_rows_without_a_balance(
    db: Session, ledger: tuple[LedgerService, Tenant, Product]
) -> None:
    _, tenant, product = ledger
    factories.make_movement(db, tenant, product, quantity_delta=D("4.000"))
    (mismatch,) = find_mismatches(db, tenant.id)
    assert mismatch.code == "BATCH_QTY_MISMATCH"
    assert mismatch.detail["on_hand"] == "0"


def test_reconciliation_only_looks_at_one_tenant(db: Session) -> None:
    a, b = factories.make_tenant(db), factories.make_tenant(db)
    product_b = factories.make_product(db, b)
    factories.make_movement(db, b, product_b)  # tenant B is out of balance
    assert find_mismatches(db, a.id) == []
    assert len(find_mismatches(db, b.id)) == 1


# --------------------------------------------------------------------------- concurrency


def test_two_simultaneous_sales_of_the_last_unit_let_exactly_one_through(
    committed: Callable[[], Session],
) -> None:
    setup = committed()
    with transaction(setup):
        tenant = factories.make_tenant(setup)
        committed.track(tenant.id)  # type: ignore[attr-defined]
        user = factories.make_user(setup, tenant)
        product = factories.make_product(setup, tenant)
        LedgerService(setup, tenant.id, user.id).post(
            [entry(product, "receipt", "1", cost="5.0000")]
        )

    start = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def sell(delay: float) -> None:
        session = committed()
        start.wait()
        time.sleep(delay)
        try:
            with transaction(session):
                service = LedgerService(session, tenant.id, user.id)
                service.post([entry(product, "sale", "-1", source=("sale", uuid.uuid4().hex))])
                time.sleep(0.4)  # hold the row lock so the other sale has to wait for it
            result = "sold"
        except InsufficientStockError:
            result = "short"
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=sell, args=(0.0,)),
        threading.Thread(target=sell, args=(0.1,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(outcomes) == ["short", "sold"]
    check = committed()
    assert check.execute(
        select(StockBalance.on_hand).where(StockBalance.product_id == product.id)
    ).scalar_one() == D(0)
    assert find_mismatches(check, tenant.id) == []


def test_many_concurrent_sales_never_oversell(committed: Callable[[], Session]) -> None:
    setup = committed()
    with transaction(setup):
        tenant = factories.make_tenant(setup)
        committed.track(tenant.id)  # type: ignore[attr-defined]
        user = factories.make_user(setup, tenant)
        product = factories.make_product(setup, tenant)
        LedgerService(setup, tenant.id, user.id).post(
            [entry(product, "receipt", "5", cost="5.0000")]
        )

    results: list[str] = []
    lock = threading.Lock()

    def sell() -> None:
        session = committed()
        try:
            with transaction(session):
                LedgerService(session, tenant.id, user.id).post(
                    [entry(product, "sale", "-1", source=("sale", uuid.uuid4().hex))]
                )
            outcome = "sold"
        except InsufficientStockError:
            outcome = "short"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=sell) for _ in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results.count("sold") == 5
    assert results.count("short") == 4
    check = committed()
    assert check.execute(
        select(StockBalance.on_hand).where(StockBalance.product_id == product.id)
    ).scalar_one() == D(0)
    assert find_mismatches(check, tenant.id) == []
