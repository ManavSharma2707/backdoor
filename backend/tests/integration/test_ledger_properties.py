"""Property tests for the ledger invariants (`testing-strategy.md` section 3, items 1 to 5).

Random sequences of receipts, bills, voids, returns and adjustments run against the real
services and database. After every step the balances must equal the ledger, no balance may be
negative, bills must add up, and a shadow model kept in plain Python must agree with the
database. Bills must follow first-expired-first-out and never touch expired stock, and a void
straight after a bill must restore every balance.
"""

import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import RequestMeta
from app.core.clock import today_ist
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.models.catalogue import Product
from app.models.inventory import ProductBatch, StockBalance
from app.schemas.sales import ReturnCreate, ReturnLineIn, SaleCreate, SaleLineIn
from app.services.ledger import InsufficientStockError, LedgerService, MovementEntry
from app.services.reconciliation import find_mismatches
from app.services.sales_service import SalesService
from tests import factories

D = Decimal
EXPECTED_REFUSALS = {"INSUFFICIENT_STOCK", "CONFLICT", "RETURN_EXCEEDS_SOLD", "BATCH_EXPIRED"}
Key = tuple[uuid.UUID, uuid.UUID | None]

# --------------------------------------------------------------------------- operations

product_index = st.integers(0, 2)  # 0 and 1 are plain products, 2 is tracked by batch
sale_line = st.tuples(product_index, st.integers(1, 15), st.booleans())
sale_lines = st.lists(sale_line, min_size=1, max_size=3)
operation = st.one_of(
    st.tuples(st.just("receipt"), product_index, st.integers(1, 30), st.integers(0, 2)),
    st.tuples(st.just("sale"), sale_lines),
    st.tuples(st.just("sale_then_void"), sale_lines),
    st.tuples(st.just("void"), st.integers(0, 20)),
    st.tuples(
        st.just("return"),
        st.integers(0, 20),
        st.integers(0, 3),
        st.integers(1, 100),
        st.sampled_from(["restock", "damaged", "expired"]),
    ),
    st.tuples(
        st.just("adjust"),
        product_index,
        st.integers(-6, 6).filter(lambda n: n != 0),
        st.integers(0, 2),
    ),
)


class World:
    """A tenant with two plain products, one batch tracked product with three batches (one
    already expired), the services under test, and a shadow copy of every balance."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.tenant = factories.make_tenant(db)
        self.user = factories.make_user(db, self.tenant)
        category = factories.make_category(db, self.tenant)
        self.products: list[Product] = [
            factories.make_product(
                db, self.tenant, category=category, mrp=D("20.00"), selling_price=D("15.00")
            ),
            factories.make_product(
                db, self.tenant, category=category, mrp=D("50.00"), selling_price=D("42.50")
            ),
            factories.make_product(
                db,
                self.tenant,
                category=category,
                mrp=D("30.00"),
                selling_price=D("25.00"),
                is_batch_tracked=True,
                shelf_life_days=365,
            ),
        ]
        today = today_ist()
        self.batches: list[ProductBatch] = [
            factories.make_batch(
                db,
                self.tenant,
                self.products[2],
                batch_no="NEAR",
                expiry_date=today + timedelta(days=20),
            ),
            factories.make_batch(
                db,
                self.tenant,
                self.products[2],
                batch_no="FAR",
                expiry_date=today + timedelta(days=200),
            ),
            factories.make_batch(
                db,
                self.tenant,
                self.products[2],
                batch_no="OLD",
                expiry_date=today - timedelta(days=5),
            ),
        ]
        db.commit()
        self.ctx = TenantContext(self.tenant.id, self.user.id, "owner", RequestMeta())
        self.expected: dict[Key, Decimal] = defaultdict(lambda: D(0))
        self.bills: list[Any] = []
        self.history: list[str] = []

    # ---- helpers

    # Services keep per request state (locked balance rows), so every step gets fresh ones,
    # as every HTTP request does.
    @property
    def ledger(self) -> LedgerService:
        return LedgerService(self.db, self.tenant.id, self.user.id)

    @property
    def sales(self) -> SalesService:
        return SalesService(self.db, self.ctx)

    def key(self, product_idx: int, batch_idx: int) -> Key:
        if product_idx == 2:
            return (self.products[2].id, self.batches[batch_idx].id)
        return (self.products[product_idx].id, None)

    def actual(self) -> dict[Key, Decimal]:
        rows = self.db.execute(
            select(StockBalance).where(StockBalance.tenant_id == self.tenant.id)
        ).scalars()
        return {(r.product_id, r.batch_id): r.on_hand for r in rows}

    def refusing(self, code_set: set[str] = EXPECTED_REFUSALS) -> "_Refusal":
        return _Refusal(code_set)

    # ---- operations

    def receipt(self, p: int, qty: int, b: int) -> None:
        key = self.key(p, b)
        self.ledger.post(
            [
                MovementEntry(
                    key[0],
                    key[1],
                    "receipt",
                    D(qty),
                    "receipt",
                    uuid.uuid4().hex,
                    unit_cost=D("7.0000"),
                )
            ]
        )
        self.db.commit()
        self.expected[key] += qty

    def adjust(self, p: int, delta: int, b: int) -> None:
        key = self.key(p, b)
        try:
            self.ledger.post(
                [
                    MovementEntry(
                        key[0], key[1], "adjustment", D(delta), "adjustment", uuid.uuid4().hex
                    )
                ]
            )
        except InsufficientStockError:
            self.db.rollback()
            return
        self.db.commit()
        self.expected[key] += delta

    def request(self, lines: list[tuple[int, int, bool]]) -> SaleCreate:
        built = []
        for p, qty, override in lines:
            body = SaleLineIn(product_id=self.products[p].id, quantity=D(qty))
            if p == 2 and override:
                body = SaleLineIn(
                    product_id=self.products[2].id, quantity=D(qty), batch_id=self.batches[1].id
                )
            built.append(body)
        return SaleCreate(payment_mode="cash", lines=built)

    def sell(self, lines: list[tuple[int, int, bool]]) -> Any:
        """Create a bill, check FEFO against the stock as it was, and update the shadow."""
        before = self.actual()
        request = self.request(lines)
        with self.refusing():
            bill = self.sales.create(request)
            for item in bill.lines:
                self.expected[(item.product_id, item.batch_id)] -= D(item.quantity)
            self.check_fefo(before, request, bill)
            self.bills.append(bill)
            return bill
        return None

    def check_fefo(self, before: dict[Key, Decimal], request: SaleCreate, bill: Any) -> None:
        tracked = self.products[2].id
        overridden = any(
            line.batch_id is not None for line in request.lines if line.product_id == tracked
        )
        taken: dict[uuid.UUID, Decimal] = defaultdict(lambda: D(0))
        for item in bill.lines:
            if item.product_id == tracked and item.batch_id is not None:
                taken[item.batch_id] += D(item.quantity)
        today = today_ist()
        by_id = {b.id: b for b in self.batches}
        # Expired stock is never sold, however the batch was chosen.
        for batch_id in taken:
            assert by_id[batch_id].expiry_date > today, "an expired batch was sold"
        if overridden:
            return
        sellable = sorted(
            (b for b in self.batches if b.expiry_date > today),
            key=lambda b: (b.expiry_date, b.batch_no),
        )
        for i, later in enumerate(sellable):
            if taken.get(later.id, D(0)) > 0:
                for earlier in sellable[:i]:
                    stock = before.get((tracked, earlier.id), D(0))
                    assert taken.get(earlier.id, D(0)) == stock, (
                        "FEFO broken: drew from a later batch while an earlier one had stock"
                    )

    def sell_then_void(self, lines: list[tuple[int, int, bool]]) -> None:
        before = self.actual()
        bill = self.sell(lines)
        if bill is None:
            return
        with self.refusing():
            self.sales.void(bill.id, "Property test void")
            for item in bill.lines:
                self.expected[(item.product_id, item.batch_id)] += D(item.quantity)
            after = self.actual()
            keys = set(before) | set(after)
            assert {k: after.get(k, D(0)) for k in keys} == {
                k: before.get(k, D(0)) for k in keys
            }, "a void did not restore the balances to what they were before the bill"

    def void(self, index: int) -> None:
        if not self.bills:
            return
        bill = self.bills[index % len(self.bills)]
        with self.refusing():
            self.sales.void(bill.id, "Property test void")
            for item in bill.lines:
                self.expected[(item.product_id, item.batch_id)] += D(item.quantity)

    def give_back(self, bill_index: int, line_index: int, percent: int, disposition: str) -> None:
        if not self.bills:
            return
        bill = self.sales.get(self.bills[bill_index % len(self.bills)].id)
        item = bill.lines[line_index % len(bill.lines)]
        remaining = D(item.quantity) - D(item.returned_qty)
        quantity = (remaining * percent / 100).quantize(D("0.001"))
        if quantity <= 0:
            quantity = remaining
        if quantity <= 0:
            return
        body = ReturnCreate(
            reason="Property test return",
            lines=[ReturnLineIn(sale_line_id=item.id, quantity=quantity, disposition=disposition)],  # type: ignore[arg-type]
        )
        with self.refusing():
            self.sales.create_return(bill.id, body)
            if disposition == "restock":
                self.expected[(item.product_id, item.batch_id)] += quantity

    # ---- checks

    def check(self) -> None:
        assert find_mismatches(self.db, self.tenant.id) == [], "balances and ledger disagree"
        actual = self.actual()
        assert all(v >= 0 for v in actual.values()), "a balance went negative"
        keys = set(actual) | set(self.expected)
        wrong = {
            k: (actual.get(k, D(0)), self.expected.get(k, D(0)))
            for k in keys
            if actual.get(k, D(0)) != self.expected.get(k, D(0))
        }
        assert not wrong, f"database and shadow model disagree: {wrong}"


class _Refusal:
    """Swallow the refusals a random sequence is expected to hit (no stock, already void)."""

    def __init__(self, codes: set[str]) -> None:
        self.codes = codes

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return isinstance(exc, AppError) and exc.code.value in self.codes


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(operations=st.lists(operation, min_size=1, max_size=12))
def test_any_sequence_of_valid_operations_keeps_the_ledger_consistent(
    db: Session, operations: list[tuple[Any, ...]]
) -> None:
    world = World(db)
    for op in operations:
        name, *args = op
        match name:
            case "receipt":
                world.receipt(*args)
            case "sale":
                world.sell(*args)
            case "sale_then_void":
                world.sell_then_void(*args)
            case "void":
                world.void(*args)
            case "return":
                world.give_back(*args)
            case "adjust":
                world.adjust(*args)
        world.history.append(name)
        world.check()


def test_the_property_test_really_exercises_sales_voids_and_returns(db: Session) -> None:
    """A fixed script through the same machinery, so a silent no-op test cannot pass."""
    world = World(db)
    world.receipt(0, 20, 0)
    world.receipt(2, 10, 0)  # NEAR
    world.receipt(2, 10, 1)  # FAR
    world.receipt(2, 4, 2)  # OLD, expired: stays on the shelf, is never sold
    world.sell([(0, 5, False), (2, 14, False)])
    assert world.expected[(world.products[2].id, world.batches[0].id)] == 0
    assert world.expected[(world.products[2].id, world.batches[1].id)] == 6
    world.give_back(0, 0, 100, "restock")
    world.sell_then_void([(2, 6, True)])
    world.void(0)
    world.check()
    assert len(world.bills) == 2
    world.expected[(world.products[0].id, None)] += 1  # the check really compares
    with pytest.raises(AssertionError):
        world.check()
