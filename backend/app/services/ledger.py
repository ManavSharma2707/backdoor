"""The stock ledger: the only code that writes `inventory_movements` and `stock_balances`.

Every stock change is a signed movement row. `stock_balances` is a cache of the ledger kept in
the same transaction. Before any balance changes, all balance rows of the products involved are
locked with `SELECT ... FOR UPDATE` in one statement ordered by key, so concurrent requests queue
up instead of overselling, and two requests can never lock rows in opposite orders.

The rules themselves (signs, average cost, FEFO) are pure functions in
`app/engine/ledger_rules.py`. This class applies them to the database.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.timeutil import ist_date
from app.engine.ledger_rules import (
    COST_SETTING_TYPES,
    LedgerRuleError,
    check_movement,
    weighted_average_cost,
)
from app.models.inventory import InventoryMovement, StockBalance

ZERO = Decimal(0)
QTY_PLACES = Decimal("0.001")

BalanceKey = tuple[uuid.UUID, uuid.UUID | None]


@dataclass(frozen=True)
class MovementEntry:
    """One stock change to post. `quantity_delta` is signed."""

    product_id: uuid.UUID
    batch_id: uuid.UUID | None
    movement_type: str
    quantity_delta: Decimal
    source_type: str
    source_id: str
    unit_cost: Decimal | None = None
    reason_code: str | None = None
    note: str | None = None
    reverses_movement_id: int | None = None
    occurred_at: datetime | None = None

    @property
    def key(self) -> BalanceKey:
        return (self.product_id, self.batch_id)


@dataclass(frozen=True)
class Shortfall:
    product_id: uuid.UUID
    batch_id: uuid.UUID | None
    requested: Decimal
    available: Decimal


class InsufficientStockError(Exception):
    """A movement would take a balance below zero. Nothing was written."""

    def __init__(self, shortfalls: Sequence[Shortfall]) -> None:
        super().__init__(f"Insufficient stock for {len(shortfalls)} balance(s)")
        self.shortfalls = tuple(shortfalls)


def _sort_key(key: BalanceKey) -> tuple[str, str]:
    return (str(key[0]), "" if key[1] is None else str(key[1]))


class LedgerService:
    def __init__(self, session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._locked_products: set[uuid.UUID] = set()
        self._balances: dict[BalanceKey, StockBalance] = {}

    # ------------------------------------------------------------------ locking and reads

    def lock_products(self, product_ids: Iterable[uuid.UUID]) -> None:
        """Lock every balance row of these products (all batches) until the transaction ends.

        One statement, ordered by product then batch, so every request takes locks in the same
        order. Products already locked by this instance are skipped.
        """
        wanted = set(product_ids) - self._locked_products
        if not wanted:
            return
        stmt = (
            select(StockBalance)
            .where(StockBalance.tenant_id == self.tenant_id, StockBalance.product_id.in_(wanted))
            .order_by(StockBalance.product_id, StockBalance.batch_id.nulls_first())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for row in self.session.execute(stmt).scalars():
            self._balances[(row.product_id, row.batch_id)] = row
        self._locked_products |= wanted

    def balance(self, product_id: uuid.UUID, batch_id: uuid.UUID | None) -> StockBalance | None:
        self.lock_products([product_id])
        return self._balances.get((product_id, batch_id))

    def on_hand(self, product_id: uuid.UUID, batch_id: uuid.UUID | None) -> Decimal:
        row = self.balance(product_id, batch_id)
        return ZERO if row is None else row.on_hand

    def product_balances(self, product_id: uuid.UUID) -> list[StockBalance]:
        """All locked balance rows of one product, batch rows included."""
        self.lock_products([product_id])
        return [row for (pid, _), row in self._balances.items() if pid == product_id]

    def _pick_up_new_rows(self, entries: Sequence[MovementEntry]) -> None:
        """Another service in the same transaction may have created a balance row after this
        instance locked its product. Load such rows so their stock is not mistaken for zero."""
        missing = {entry.key for entry in entries} - set(self._balances)
        for key in missing:
            row = self.session.execute(
                select(StockBalance)
                .where(
                    StockBalance.tenant_id == self.tenant_id,
                    StockBalance.product_id == key[0],
                    StockBalance.batch_id.is_(None)
                    if key[1] is None
                    else StockBalance.batch_id == key[1],
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if row is not None:
                self._balances[key] = row

    def _ensure_row(self, key: BalanceKey) -> StockBalance:
        """The locked balance row for `key`, created empty when it does not exist yet."""
        existing = self._balances.get(key)
        if existing is not None:
            return existing
        self.session.execute(
            pg_insert(StockBalance)
            .values(tenant_id=self.tenant_id, product_id=key[0], batch_id=key[1], on_hand=ZERO)
            .on_conflict_do_nothing()
        )
        stmt = (
            select(StockBalance)
            .where(
                StockBalance.tenant_id == self.tenant_id,
                StockBalance.product_id == key[0],
                StockBalance.batch_id.is_(None)
                if key[1] is None
                else StockBalance.batch_id == key[1],
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = self.session.execute(stmt).scalar_one()
        self._balances[key] = row
        return row

    # ------------------------------------------------------------------ writing

    def post(self, entries: Sequence[MovementEntry]) -> list[InventoryMovement]:
        """Write movements and move balances, all or nothing.

        Raises `InsufficientStockError` (before writing anything) when any balance would go
        below zero, and `LedgerRuleError` for a movement that breaks a sign or precision rule.
        """
        if not entries:
            return []
        for entry in entries:
            check_movement(entry.movement_type, entry.quantity_delta)
            if entry.quantity_delta != entry.quantity_delta.quantize(QTY_PLACES):
                raise LedgerRuleError("Quantities have at most 3 decimal places")

        self.lock_products(entry.product_id for entry in entries)
        self._pick_up_new_rows(entries)
        self._check_no_overdraw(entries)

        movements: list[InventoryMovement] = []
        for entry in entries:
            row = self._ensure_row(entry.key)
            occurred = entry.occurred_at or now_utc()
            unit_cost = entry.unit_cost if entry.unit_cost is not None else row.avg_unit_cost
            if entry.movement_type in COST_SETTING_TYPES:
                row.avg_unit_cost = weighted_average_cost(
                    row.on_hand, row.avg_unit_cost, entry.quantity_delta, unit_cost
                )
            row.on_hand = row.on_hand + entry.quantity_delta
            row.last_movement_at = occurred
            movements.append(
                InventoryMovement(
                    tenant_id=self.tenant_id,
                    product_id=entry.product_id,
                    batch_id=entry.batch_id,
                    movement_type=entry.movement_type,
                    quantity_delta=entry.quantity_delta,
                    unit_cost=unit_cost,
                    occurred_at=occurred,
                    business_date=ist_date(occurred),
                    source_type=entry.source_type,
                    source_id=entry.source_id,
                    reason_code=entry.reason_code,
                    note=entry.note,
                    reverses_movement_id=entry.reverses_movement_id,
                    created_by=self.user_id,
                )
            )
        self.session.add_all(movements)
        self.session.flush()
        return movements

    def _check_no_overdraw(self, entries: Sequence[MovementEntry]) -> None:
        """Dry run of the whole batch of entries. Collects every shortfall, not just the first."""
        start: dict[BalanceKey, Decimal] = {}
        running: dict[BalanceKey, Decimal] = {}
        lowest: dict[BalanceKey, Decimal] = {}
        for entry in entries:
            key = entry.key
            if key not in start:
                row = self._balances.get(key)
                start[key] = running[key] = lowest[key] = ZERO if row is None else row.on_hand
            running[key] += entry.quantity_delta
            lowest[key] = min(lowest[key], running[key])
        short = [key for key in sorted(start, key=_sort_key) if lowest[key] < 0]
        if short:
            raise InsufficientStockError(
                [
                    Shortfall(
                        product_id=key[0],
                        batch_id=key[1],
                        requested=start[key] - lowest[key],
                        available=start[key],
                    )
                    for key in short
                ]
            )

    # ------------------------------------------------------------------ helpers for callers

    def movements_for(
        self, source_type: str, source_id: str, *, movement_type: str | None = None
    ) -> list[InventoryMovement]:
        """The movements one document wrote, oldest first."""
        stmt = select(InventoryMovement).where(
            InventoryMovement.tenant_id == self.tenant_id,
            InventoryMovement.source_type == source_type,
            InventoryMovement.source_id == source_id,
        )
        if movement_type is not None:
            stmt = stmt.where(InventoryMovement.movement_type == movement_type)
        return list(self.session.execute(stmt.order_by(InventoryMovement.id)).scalars())


def business_date_of(occurred_at: datetime | None) -> date:
    return ist_date(occurred_at or now_utc())
