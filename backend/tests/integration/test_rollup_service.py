"""The rollup service against a real database, with a ledger small enough to check by hand."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.catalogue import Product
from app.models.inventory import StockoutInterval
from app.models.tenancy import Tenant
from app.services.rollup import RollupService
from tests import factories

OPENING = date(2026, 1, 4)  # Sunday, the day before the first stats row
MONDAY = date(2026, 1, 5)


def day(n: int) -> date:
    return MONDAY + timedelta(days=n)


def stats(
    db: Session, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> dict[date, tuple[object, ...]]:
    rows = db.execute(
        text(
            """
            SELECT stat_date, units_sold, units_returned, revenue, avg_price, opening_on_hand,
                   closing_on_hand, receipts_qty, availability_state, is_censored, promo_active,
                   event_keys
            FROM daily_product_stats WHERE tenant_id = :t AND product_id = :p ORDER BY stat_date
            """
        ),
        {"t": tenant_id, "p": product_id},
    ).all()
    return {r[0]: tuple(r[1:]) for r in rows}


def sell(db: Session, tenant: Tenant, product: Product, on: date, qty: int, total: str) -> None:
    sale = factories.make_sale(
        db, tenant, business_date=on, total=Decimal(total), subtotal=Decimal(total)
    )
    factories.make_sale_line(
        db,
        tenant,
        sale,
        product,
        quantity=Decimal(qty),
        line_total=Decimal(total),
        business_date=on,
    )
    factories.make_movement(
        db,
        tenant,
        product,
        movement_type="sale",
        quantity_delta=Decimal(-qty),
        business_date=on,
        source_type="sale",
        source_id=f"s-{on}-{qty}",
    )


def build(db: Session) -> tuple[Tenant, Product]:
    tenant = factories.make_tenant(db)
    product = factories.make_product(db, tenant)
    factories.make_movement(db, tenant, product, quantity_delta=Decimal(10), business_date=OPENING)
    sell(db, tenant, product, day(0), 4, "38.00")
    sell(db, tenant, product, day(1), 6, "57.00")
    factories.make_movement(
        db,
        tenant,
        product,
        movement_type="receipt",
        quantity_delta=Decimal(20),
        business_date=day(3),
        source_type="receipt",
        source_id="gr-1",
    )
    sell(db, tenant, product, day(4), 5, "47.50")
    return tenant, product


def test_rebuild_matches_a_hand_computed_week(db: Session) -> None:
    tenant, product = build(db)
    result = RollupService(db, tenant.id).rebuild(None, day(5))
    assert (result.start, result.end, result.rows) == (MONDAY, day(5), 6)
    rows = stats(db, tenant.id, product.id)
    assert rows[day(0)][:2] == (Decimal("4.000"), Decimal("0.000"))
    assert rows[day(0)][2:5] == (Decimal("38.00"), Decimal("9.5000"), Decimal("10.000"))
    assert [rows[day(i)][7] for i in range(6)] == [
        "available",
        "sold_out_during_day",
        "stocked_out_all_day",
        "available",
        "available",
        "available",
    ]
    assert [rows[day(i)][5] for i in range(6)] == [Decimal(x) for x in (6, 0, 0, 20, 15, 15)]
    assert rows[day(3)][6] == Decimal("20.000")  # receipts
    assert [rows[day(i)][8] for i in (1, 2, 3)] == [True, True, False]  # censored
    assert rows[day(2)][3] is None  # no sales, no average price


def test_rebuild_is_idempotent(db: Session) -> None:
    tenant, product = build(db)
    svc = RollupService(db, tenant.id)
    svc.rebuild(None, day(5))
    first = stats(db, tenant.id, product.id)
    svc.rebuild(None, day(5))
    assert stats(db, tenant.id, product.id) == first


def test_incremental_update_adds_days_and_recomputes_the_lookback(db: Session) -> None:
    tenant, product = build(db)
    svc = RollupService(db, tenant.id)
    svc.rebuild(None, day(3))
    assert svc.last_rolled() == day(3)
    # A recorded stockout arrives late and changes a day that was already rolled up.
    db.add(
        StockoutInterval(
            tenant_id=tenant.id,
            product_id=product.id,
            start_date=day(3),
            end_date=day(3),
            source="recorded",
        )
    )
    db.flush()
    result = svc.update(day(5))
    assert (result.start, result.end) == (MONDAY, day(5))
    rows = stats(db, tenant.id, product.id)
    assert len(rows) == 6
    # The owner said it was out that day, so the day is not trusted even though a delivery came.
    assert rows[day(3)][7] == "stocked_out_all_day"
    assert svc.last_rolled() == day(5)


def test_recorded_stockout_and_inferred_interval(db: Session) -> None:
    tenant, product = build(db)
    svc = RollupService(db, tenant.id)
    # A write off empties the shelf on day 4, so days 5 to 8 are an unrecorded stockout.
    factories.make_movement(
        db,
        tenant,
        product,
        movement_type="damage",
        quantity_delta=Decimal(-15),
        business_date=day(4),
        source_type="adjustment",
        source_id="adj-1",
    )
    result = svc.rebuild(None, day(8))
    assert result.inferred_intervals == 1  # day 2 is a single day, days 5 to 8 are a run
    runs = db.execute(
        text(
            "SELECT start_date, end_date FROM stockout_intervals "
            "WHERE tenant_id = :t AND source = 'inferred' ORDER BY start_date"
        ),
        {"t": tenant.id},
    ).all()
    assert runs == [(day(5), None)]


def test_promotion_and_event_keys_are_flagged(db: Session) -> None:
    tenant, product = build(db)
    db.execute(
        text(
            "INSERT INTO promotions (tenant_id, name, kind, category_id, discount_pct, "
            "starts_on, ends_on) VALUES (:t, 'Offer', 'discount', :c, 10, :s, :e)"
        ),
        {"t": tenant.id, "c": product.category_id, "s": day(1), "e": day(2)},
    )
    RollupService(db, tenant.id).rebuild(None, day(5))
    rows = stats(db, tenant.id, product.id)
    assert [rows[day(i)][9] for i in range(6)] == [False, True, True, False, False, False]
    # Winter runs all through January. Makar Sankranti (14 Jan 2026) has a 5 day pre window, so
    # 9 Jan is inside it and 5 Jan is not.
    assert rows[day(0)][10] == ["winter"]
    db.execute(text("DELETE FROM daily_product_stats WHERE tenant_id = :t"), {"t": tenant.id})
    RollupService(db, tenant.id).rebuild(date(2026, 1, 8), date(2026, 1, 15))
    later = stats(db, tenant.id, product.id)
    assert later[date(2026, 1, 8)][10] == ["winter"]
    assert later[date(2026, 1, 9)][10] == ["makar_sankranti", "winter"]
    assert "makar_sankranti" in later[date(2026, 1, 15)][10]


def test_new_product_is_rolled_over_its_whole_history(db: Session) -> None:
    tenant, _product = build(db)
    svc = RollupService(db, tenant.id)
    svc.rebuild(None, day(5))
    other = factories.make_product(db, tenant)
    result = svc.update(day(7))
    rows = stats(db, tenant.id, other.id)
    assert len(rows) == 8
    assert all(v[7] == "unknown" for v in rows.values())
    assert result.products >= 2


def test_empty_tenant_rolls_nothing(db: Session) -> None:
    tenant = factories.make_tenant(db)
    result = RollupService(db, tenant.id).update(day(3))
    assert result.rows == 0
    assert result.start is None
