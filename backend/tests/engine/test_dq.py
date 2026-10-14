"""Every data quality code with the case that triggers it and the case that does not."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.engine import dq
from app.engine.calendar import CalendarEvent
from app.engine.deadstock import abc_classes
from app.engine.inputs import BatchInfo, ProductInfo, SettingsInfo, SupplierInfo, TermInfo

AS_OF = date(2026, 10, 12)
SETTINGS = SettingsInfo()
SUPPLIER = SupplierInfo(uuid.uuid4(), "S1", "Metro Traders", 2, (1, 4))
SUPPLIER_NO_LEAD = SupplierInfo(uuid.uuid4(), "S2", "Cash Vendor", None, None)
TERM = TermInfo(SUPPLIER.id, Decimal("8.00"), Decimal("10"), Decimal("0"), None)


def product(name: str = "Biscuits", **overrides: object) -> ProductInfo:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "sku": "SKU-1",
        "name": name,
        "category_id": uuid.uuid4(),
        "category_slug": "biscuits",
        "category_name": "Biscuits",
        "is_active": True,
        "is_batch_tracked": False,
        "shelf_life_days": None,
        "min_stock_qty": 0.0,
        "is_seasonal": False,
        "launched_on": date(2025, 1, 1),
        "first_seen": date(2025, 1, 1),
        "selling_price": Decimal("12.00"),
        "mrp": Decimal("12.00"),
        "base_unit": "pack",
        "pack_label": None,
        "avg_cost": Decimal("8.00"),
        "term": TERM,
        "last_count_date": AS_OF - timedelta(days=5),
    }
    values.update(overrides)
    return ProductInfo(**values)  # type: ignore[arg-type]


def codes(findings: list[dq.DqFinding]) -> list[str]:
    return sorted(f.code for f in findings)


def catalogue(
    products: list[ProductInfo],
    abc: dict[uuid.UUID, str] | None = None,
    settings: SettingsInfo = SETTINGS,
) -> list[dq.DqFinding]:
    suppliers = {SUPPLIER.id: SUPPLIER, SUPPLIER_NO_LEAD.id: SUPPLIER_NO_LEAD}
    return dq.check_catalogue(products, suppliers, settings, abc or {}, AS_OF)


def test_a_healthy_product_has_no_findings() -> None:
    assert catalogue([product()]) == []


def test_missing_supplier_and_cost_for_a_product_without_a_term() -> None:
    found = catalogue([product(term=None)])
    assert {"MISSING_SUPPLIER", "MISSING_COST", "MISSING_LEAD_TIME"} <= set(codes(found))
    assert all(
        f.severity == "error" for f in found if f.code in ("MISSING_SUPPLIER", "MISSING_COST")
    )


def test_zero_price_is_a_missing_cost() -> None:
    term = TermInfo(SUPPLIER.id, Decimal(0), Decimal("10"), Decimal(0), None)
    assert "MISSING_COST" in codes(catalogue([product(term=term)]))


def test_lead_time_resolution_decides_missing_lead_time() -> None:
    cash_term = TermInfo(SUPPLIER_NO_LEAD.id, Decimal("8"), Decimal("1"), Decimal(0), None)
    assert codes(catalogue([product(term=cash_term)])) == ["MISSING_LEAD_TIME"]
    own = TermInfo(SUPPLIER_NO_LEAD.id, Decimal("8"), Decimal("1"), Decimal(0), 0)
    assert catalogue([product(term=own)]) == []  # zero is a real delivery time


def test_missing_expiry_for_stock_without_a_batch() -> None:
    loose = BatchInfo(None, None, 12.0, None, Decimal(0))
    tracked = product(is_batch_tracked=True, batches=(loose,))
    assert "MISSING_EXPIRY" in codes(catalogue([tracked]))
    plain = product(is_batch_tracked=False, batches=(loose,))
    assert "MISSING_EXPIRY" not in codes(catalogue([plain]))


def test_stale_count_only_for_a_class_products() -> None:
    old = product(last_count_date=AS_OF - timedelta(days=45))
    never = product(last_count_date=None)
    abc = {old.id: "A", never.id: "A"}
    assert codes(catalogue([old, never], abc)) == ["STALE_STOCK_COUNT"] * 2
    assert catalogue([old], {old.id: "B"}) == []
    recent = product(last_count_date=AS_OF - timedelta(days=30))
    assert catalogue([recent], {recent.id: "A"}) == []  # exactly the limit is still fine


def test_price_anomaly_for_a_big_jump_or_selling_below_cost() -> None:
    jump = product(previous_term_prices=(Decimal("5.00"),))  # 5 to 8 is 60 percent
    assert codes(catalogue([jump])) == ["PRICE_ANOMALY"]
    small = product(previous_term_prices=(Decimal("7.50"),))  # 6.7 percent, like S11
    assert catalogue([small]) == []
    loss = product(selling_price=Decimal("6.00"))
    found = catalogue([loss])
    assert codes(found) == ["PRICE_ANOMALY"]
    assert found[0].detail["kind"] == "selling_below_cost"


def test_new_product_by_age() -> None:
    recent = product(launched_on=AS_OF - timedelta(days=35))
    assert codes(catalogue([recent])) == ["NEW_PRODUCT"]
    unknown_age = product(launched_on=None, first_seen=None)
    assert codes(catalogue([unknown_age])) == ["NEW_PRODUCT"]


def test_inactive_products_are_not_checked() -> None:
    assert catalogue([product(term=None, is_active=False)]) == []


def test_history_checks() -> None:
    p = product()
    facts = {p.id: dq.HistoryFacts(trusted_days=12, censored_share=0.45)}
    assert codes(dq.check_history([p], facts, AS_OF, 60)) == ["CENSORED_HISTORY", "SPARSE_HISTORY"]
    # A new product is expected to have little history, that is the NEW_PRODUCT note instead.
    new = product(launched_on=AS_OF - timedelta(days=20))
    assert dq.check_history([new], {new.id: dq.HistoryFacts(12, 0.0)}, AS_OF, 60) == []
    ok = {p.id: dq.HistoryFacts(trusted_days=150, censored_share=0.30)}
    assert dq.check_history([p], ok, AS_OF, 60) == []


def test_negative_stock_and_ledger_mismatch() -> None:
    pid = uuid.uuid4()
    found = dq.check_stock(
        [dq.StockIssue(pid, None, -2.0)],
        [dq.StockIssue(pid, None, 5.0, 4.0), dq.StockIssue(pid, uuid.uuid4(), 3.0, 1.0)],
        {pid: "Biscuits"},
    )
    assert codes(found) == ["BATCH_QTY_MISMATCH", "NEGATIVE_STOCK"]  # one note per product


def test_unrecorded_stockouts_need_three_days_and_no_recorded_interval() -> None:
    pid = uuid.uuid4()
    labels = {pid: "Biscuits"}
    recent = AS_OF - timedelta(days=20)
    rows = [
        dq.InferredStockout(pid, recent, recent + timedelta(days=4), False),
        dq.InferredStockout(uuid.uuid4(), recent, recent + timedelta(days=4), True),
        dq.InferredStockout(uuid.uuid4(), recent, recent + timedelta(days=1), False),  # 2 days
        dq.InferredStockout(
            uuid.uuid4(), AS_OF - timedelta(days=300), AS_OF - timedelta(days=290), False
        ),  # too old
    ]
    found = dq.check_unrecorded_stockouts(rows, labels, AS_OF)
    assert codes(found) == ["UNRECORDED_STOCKOUT_SUSPECTED"]
    assert found[0].entity_id == pid
    open_ended = dq.InferredStockout(pid, AS_OF - timedelta(days=5), None, False)
    assert len(dq.check_unrecorded_stockouts([open_ended], labels, AS_OF)) == 1


def test_overdue_orders_and_exception_receipts() -> None:
    po = dq.OverduePo(uuid.uuid4(), "PO2610-0007", "Metro Traders", AS_OF - timedelta(days=6), 6)
    ex = dq.ExceptionReceipts(uuid.uuid4(), "Cash Vendor", 3)
    found = dq.check_purchasing([po], [ex])
    assert codes(found) == ["PO_OVERDUE", "RECEIPT_EXCEEDS_ORDER"]
    assert "6 days late" in found[0].message


def test_duplicate_sales_and_calendar() -> None:
    dup = dq.DuplicateBill(uuid.uuid4(), "B2610-00002", "B2610-00001")
    assert codes(dq.check_duplicate_sales([dup])) == ["DUPLICATE_SALE_SUSPECT"]
    near = CalendarEvent(
        "d",
        "diwali",
        "Diwali",
        "festival",
        AS_OF + timedelta(days=25),
        AS_OF + timedelta(days=29),
        14,
        4,
        2,
    )
    assert dq.check_calendar([near], AS_OF) == []
    far = CalendarEvent(
        "d",
        "diwali",
        "Diwali",
        "festival",
        AS_OF + timedelta(days=90),
        AS_OF + timedelta(days=94),
        14,
        4,
        2,
    )
    assert codes(dq.check_calendar([far], AS_OF)) == ["CALENDAR_STALE"]
    assert codes(dq.check_calendar([], AS_OF)) == ["CALENDAR_STALE"]


def test_every_code_has_a_severity_and_the_table_is_complete() -> None:
    assert set(dq.SEVERITIES) == set(dq.CODES)
    assert len(dq.CODES) == 19
    assert {dq.SEVERITIES[c] for c in dq.CODES} == {"error", "warning", "info"}


def test_summary_groups_by_code_and_orders_by_severity() -> None:
    a, b = product("A"), product("B")
    found = catalogue(
        [
            product(term=None, name="A"),
            product(term=None, name="B"),
            product(previous_term_prices=(Decimal("5.00"),), name="C"),
        ]
    )
    notes = dq.summarise(found)
    assert [n["severity"] for n in notes] == sorted(
        (n["severity"] for n in notes), key={"error": 0, "warning": 1, "info": 2}.get
    )
    by_code = {n["code"]: n for n in notes}
    assert by_code["MISSING_SUPPLIER"]["count"] == 2
    assert "2 products" in by_code["MISSING_SUPPLIER"]["message"]
    assert by_code["PRICE_ANOMALY"]["count"] == 1
    assert a.id != b.id


def test_messages_follow_the_copy_rules() -> None:
    from app.core.text import BANNED_WORDS

    p = product(term=None, launched_on=AS_OF - timedelta(days=10))
    found = catalogue([p]) + dq.check_calendar([], AS_OF)
    for f in found:
        for text in (f.message, f.fix_hint or ""):
            assert "—" not in text
            assert "–" not in text
            assert "!" not in text
            assert not any(w in text.lower().split() for w in BANNED_WORDS)


def test_abc_classes_by_cumulative_share() -> None:
    ids = [uuid.uuid4() for _ in range(6)]
    revenue = dict(zip(ids, [500.0, 200.0, 150.0, 80.0, 70.0, 0.0], strict=True))
    got = abc_classes(revenue)
    # Shares: 0.5, 0.2, 0.15, 0.08, 0.07. Before each: 0, .5, .7, .85, .93.
    assert [got[i] for i in ids] == ["A", "A", "B", "B", "C", "C"]


def test_abc_best_seller_is_always_an_a() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    assert abc_classes({a: 1000.0, b: 10.0}) == {a: "A", b: "C"}
    assert abc_classes({a: 0.0}) == {a: "C"}
    assert abc_classes({}) == {}
