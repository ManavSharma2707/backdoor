"""CHECK constraints, partial unique indexes, generated columns, triggers and views."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.agents import ChatMessage, ChatThread, KnowledgeChunk, KnowledgeDocument
from app.models.catalogue import Product, ProductEquivalent
from app.models.intelligence import DataQualityIssue
from app.models.inventory import StockCount, StockCountLine, StockoutInterval
from app.models.ops import JobRun
from app.models.purchasing import GoodsReceipt
from app.models.reference import CalendarEvent
from app.models.sales import Promotion
from app.models.suppliers import Supplier
from app.models.tenancy import BusinessSettings, Tenant, User
from tests import factories
from tests.conftest import TenantBundle, TwoTenants, rejected

Check = Callable[[Session, TenantBundle], Any]


def _add(db: Session, obj: Any) -> Any:
    db.add(obj)
    db.flush()
    return obj


# Each case builds one row that breaks exactly one CHECK. The key is the constraint name.
CHECK_CASES: dict[str, Check] = {
    "ck_products_prices_non_negative": lambda db, b: factories.make_product(
        db, b.tenant, selling_price=Decimal("-1")
    ),
    "ck_products_base_unit_valid": lambda db, b: factories.make_product(
        db, b.tenant, base_unit="crate"
    ),
    "ck_products_schedule_class_valid": lambda db, b: factories.make_product(
        db, b.tenant, schedule_class="Z"
    ),
    "ck_sale_lines_quantity_positive": lambda db, b: factories.make_sale_line(
        db, b.tenant, factories.make_sale(db, b.tenant), b.product, quantity=Decimal(0)
    ),
    "ck_sale_lines_returned_within_sold": lambda db, b: factories.make_sale_line(
        db,
        b.tenant,
        factories.make_sale(db, b.tenant),
        b.product,
        quantity=Decimal(2),
        returned_qty=Decimal(3),
    ),
    "ck_sales_payment_mode_valid": lambda db, b: factories.make_sale(
        db, b.tenant, payment_mode="barter"
    ),
    "ck_sales_status_valid": lambda db, b: factories.make_sale(db, b.tenant, status="lost"),
    "ck_stock_balances_on_hand_non_negative": lambda db, b: factories.make_balance(
        db, b.tenant, b.product, on_hand=Decimal("-0.001")
    ),
    "ck_inventory_movements_delta_not_zero": lambda db, b: factories.make_movement(
        db, b.tenant, b.product, quantity_delta=Decimal(0)
    ),
    "ck_inventory_movements_movement_type_valid": lambda db, b: factories.make_movement(
        db, b.tenant, b.product, movement_type="teleport"
    ),
    "ck_supplier_product_terms_pack_size_positive": lambda db, b: factories.make_terms(
        db, b.tenant, b.supplier, b.product, pack_size=Decimal(0)
    ),
    "ck_purchase_order_lines_quantity_positive": lambda db, b: factories.make_po_line(
        db,
        b.tenant,
        factories.make_po(db, b.tenant, b.supplier),
        b.product,
        quantity_ordered=Decimal(0),
    ),
    "ck_purchase_orders_status_valid": lambda db, b: factories.make_po(
        db, b.tenant, b.supplier, status="lost"
    ),
    "ck_goods_receipts_exception_needs_note": lambda db, b: _add(
        db,
        GoodsReceipt(
            tenant_id=b.tenant.id,
            supplier_id=b.supplier.id,
            receipt_no=f"R-{factories.short_id()}",
            received_on=factories.BUSINESS_DATE,
            is_exception=True,
        ),
    ),
    "ck_promotions_one_target": lambda db, b: _add(
        db,
        Promotion(
            tenant_id=b.tenant.id,
            name="Both targets",
            kind="discount",
            product_id=b.product.id,
            category_id=b.category.id,
            discount_pct=Decimal(10),
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 10, 31),
        ),
    ),
    "ck_promotions_ends_after_start": lambda db, b: _add(
        db,
        Promotion(
            tenant_id=b.tenant.id,
            name="Backwards",
            kind="discount",
            product_id=b.product.id,
            discount_pct=Decimal(10),
            starts_on=date(2026, 10, 31),
            ends_on=date(2026, 10, 1),
        ),
    ),
    "ck_product_equivalents_not_self": lambda db, b: _add(
        db,
        ProductEquivalent(
            tenant_id=b.tenant.id, product_id=b.product.id, equivalent_product_id=b.product.id
        ),
    ),
    "ck_suppliers_delivery_weekdays_iso": lambda db, b: factories.make_supplier(
        db, b.tenant, delivery_weekdays=[0, 8]
    ),
    "ck_stockout_intervals_end_after_start": lambda db, b: _add(
        db,
        StockoutInterval(
            tenant_id=b.tenant.id,
            product_id=b.product.id,
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 1),
            source="recorded",
        ),
    ),
    "ck_calendar_events_end_after_start": lambda db, b: _add(
        db,
        CalendarEvent(
            slug=f"bad-{factories.short_id()}",
            event_key="bad",
            name="Bad",
            kind="festival",
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 9),
        ),
    ),
    "ck_business_settings_pack_rounding_valid": lambda db, b: _add(
        db, BusinessSettings(tenant_id=b.tenant.id, pack_rounding="sideways")
    ),
    "ck_users_role_valid": lambda db, b: factories.make_user(db, b.tenant, role="emperor"),
    "ck_tenants_business_type_valid": lambda db, b: factories.make_tenant(db, business_type="bank"),
    "ck_recommendation_lines_sections_valid": lambda db, b: factories.make_recommendation_line(
        db,
        b.tenant,
        factories.make_recommendation_run(db, b.tenant),
        b.product,
        sections=["buy", "yolo"],
    ),
    "ck_recommendation_lines_risk_level_valid": lambda db, b: factories.make_recommendation_line(
        db,
        b.tenant,
        factories.make_recommendation_run(db, b.tenant),
        b.product,
        risk_level="spicy",
    ),
    "ck_chat_messages_feedback_valid": lambda db, b: _chat_message_with_feedback(db, b, 2),
}


def _chat_message_with_feedback(db: Session, b: TenantBundle, feedback: int) -> Any:
    thread = _add(db, ChatThread(tenant_id=b.tenant.id, user_id=b.user.id, title="Thread"))
    return _add(
        db,
        ChatMessage(
            tenant_id=b.tenant.id,
            thread_id=thread.id,
            role="user",
            content="hello",
            feedback=feedback,
        ),
    )


@pytest.mark.parametrize("case", CHECK_CASES.values(), ids=CHECK_CASES.keys())
def test_check_constraint_rejects_bad_rows(
    db: Session, two_tenants: TwoTenants, case: Check
) -> None:
    name = next(key for key, value in CHECK_CASES.items() if value is case)
    with rejected(db, match=name):
        case(db, two_tenants.a)


# ---------------------------------------------------------------- partial unique indexes


class TestPrimaryTerm:
    def test_second_current_primary_term_for_a_product_is_rejected(self, db: Session) -> None:
        b = _bundle(db)
        other = factories.make_supplier(db, b.tenant)
        factories.make_terms(db, b.tenant, b.supplier, b.product, is_primary=True)
        with rejected(db, match="uq_supplier_product_terms_one_primary"):
            factories.make_terms(db, b.tenant, other, b.product, is_primary=True)

    def test_a_non_primary_term_is_fine(self, db: Session) -> None:
        b = _bundle(db)
        other = factories.make_supplier(db, b.tenant)
        factories.make_terms(db, b.tenant, b.supplier, b.product, is_primary=True)
        factories.make_terms(db, b.tenant, other, b.product, is_primary=False)

    def test_an_ended_primary_term_does_not_block_a_new_one(self, db: Session) -> None:
        b = _bundle(db)
        other = factories.make_supplier(db, b.tenant)
        factories.make_terms(
            db, b.tenant, b.supplier, b.product, is_primary=True, effective_to=date(2026, 6, 30)
        )
        factories.make_terms(
            db, b.tenant, other, b.product, is_primary=True, effective_from=date(2026, 7, 1)
        )

    def test_two_tenants_can_each_have_a_primary_term(
        self, db: Session, two_tenants: TwoTenants
    ) -> None:
        for side in (two_tenants.a, two_tenants.b):
            factories.make_terms(db, side.tenant, side.supplier, side.product, is_primary=True)


class TestSales:
    def test_bill_number_is_unique_per_tenant(self, db: Session, two_tenants: TwoTenants) -> None:
        factories.make_sale(db, two_tenants.a.tenant, bill_no="B-1")
        factories.make_sale(db, two_tenants.b.tenant, bill_no="B-1")
        with rejected(db, match="uq_sales_tenant_id_bill_no"):
            factories.make_sale(db, two_tenants.a.tenant, bill_no="B-1")

    def test_idempotency_key_is_unique_per_tenant(
        self, db: Session, two_tenants: TwoTenants
    ) -> None:
        factories.make_sale(db, two_tenants.a.tenant, idempotency_key="key-12345678")
        factories.make_sale(db, two_tenants.b.tenant, idempotency_key="key-12345678")
        with rejected(db, match="uq_sales_tenant_idempotency_key"):
            factories.make_sale(db, two_tenants.a.tenant, idempotency_key="key-12345678")

    def test_many_sales_without_a_key_are_fine(self, db: Session, two_tenants: TwoTenants) -> None:
        for _ in range(3):
            factories.make_sale(db, two_tenants.a.tenant, idempotency_key=None)


class TestReportsAndDecisions:
    def test_one_current_report_per_tenant_and_week(self, db: Session) -> None:
        b = _bundle(db)
        run = factories.make_recommendation_run(db, b.tenant)
        factories.make_report(db, b.tenant, run, version=1, is_current=True)
        with rejected(db, match="uq_weekly_reports_current_week"):
            factories.make_report(db, b.tenant, run, version=2, is_current=True)

    def test_superseded_versions_can_pile_up(self, db: Session) -> None:
        b = _bundle(db)
        run = factories.make_recommendation_run(db, b.tenant)
        factories.make_report(db, b.tenant, run, version=1, is_current=False)
        factories.make_report(db, b.tenant, run, version=2, is_current=False)
        factories.make_report(db, b.tenant, run, version=3, is_current=True)

    def test_same_version_twice_is_rejected(self, db: Session) -> None:
        b = _bundle(db)
        run = factories.make_recommendation_run(db, b.tenant)
        factories.make_report(db, b.tenant, run, version=1, is_current=False)
        with rejected(db, match="uq_weekly_reports_tenant_id_week_start_version"):
            factories.make_report(db, b.tenant, run, version=1, is_current=False)

    def test_one_live_decision_per_line(self, db: Session) -> None:
        b = _bundle(db)
        run = factories.make_recommendation_run(db, b.tenant)
        line = factories.make_recommendation_line(db, b.tenant, run, b.product)
        first = factories.make_decision(db, b.tenant, line, b.user)
        with rejected(db, match="uq_recommendation_decisions_live"):
            factories.make_decision(db, b.tenant, line, b.user, decision="rejected")
        first.superseded_at = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
        db.flush()
        factories.make_decision(db, b.tenant, line, b.user, decision="edited")

    def test_one_line_per_product_per_run(self, db: Session) -> None:
        b = _bundle(db)
        run = factories.make_recommendation_run(db, b.tenant)
        factories.make_recommendation_line(db, b.tenant, run, b.product)
        with rejected(db, match="uq_recommendation_lines_run_id_product_id"):
            factories.make_recommendation_line(db, b.tenant, run, b.product)


class TestNullsNotDistinct:
    def test_two_unbatched_balances_for_a_product_are_rejected(self, db: Session) -> None:
        b = _bundle(db)
        factories.make_balance(db, b.tenant, b.product, batch=None)
        with rejected(db, match="uq_stock_balances"):
            factories.make_balance(db, b.tenant, b.product, batch=None)

    def test_batched_and_unbatched_balances_can_coexist(self, db: Session) -> None:
        b = _bundle(db)
        batch = factories.make_batch(db, b.tenant, b.product)
        factories.make_balance(db, b.tenant, b.product, batch=None)
        factories.make_balance(db, b.tenant, b.product, batch=batch)

    def test_open_data_quality_issue_cannot_repeat(self, db: Session) -> None:
        b = _bundle(db)

        def issue(**kw: Any) -> DataQualityIssue:
            values: dict[str, Any] = {
                "tenant_id": b.tenant.id,
                "code": "MISSING_PRICE",
                "severity": "warning",
                "message": "No price",
            }
            return _add(db, DataQualityIssue(**{**values, **kw}))

        first = issue()
        with rejected(db, match="uq_data_quality_issues_open"):
            issue()
        first.resolved_at = datetime(2026, 10, 12, tzinfo=UTC)
        db.flush()
        issue()  # fine again once the earlier one is resolved

    def test_job_runs_with_no_tenant_cannot_repeat(self, db: Session) -> None:
        def run(**kw: Any) -> JobRun:
            values: dict[str, Any] = {
                "job_name": "monday_report",
                "run_key": "2026-10-12",
                "status": "running",
            }
            return _add(db, JobRun(**{**values, **kw}))

        run(tenant_id=None)
        with rejected(db, match="uq_job_runs"):
            run(tenant_id=None)

    def test_job_runs_for_different_tenants_are_independent(
        self, db: Session, two_tenants: TwoTenants
    ) -> None:
        for side in (two_tenants.a, two_tenants.b):
            _add(
                db,
                JobRun(
                    tenant_id=side.tenant.id,
                    job_name="monday_report",
                    run_key="2026-10-12",
                    status="running",
                ),
            )

    def test_global_knowledge_documents_are_deduplicated(self, db: Session) -> None:
        def doc() -> KnowledgeDocument:
            return _add(
                db,
                KnowledgeDocument(
                    tenant_id=None,
                    doc_type="app_knowledge",
                    title="How the plan works",
                    source_ref="plan",
                    content_hash="a" * 64,
                ),
            )

        doc()
        with rejected(db, match="uq_knowledge_documents"):
            doc()


# ---------------------------------------------------------------- generated columns, triggers, views


def test_count_line_variance_is_generated(db: Session) -> None:
    b = _bundle(db)
    count = _add(db, StockCount(tenant_id=b.tenant.id, count_date=factories.BUSINESS_DATE))
    line = _add(
        db,
        StockCountLine(
            tenant_id=b.tenant.id,
            count_id=count.id,
            product_id=b.product.id,
            system_qty=Decimal("10.000"),
            counted_qty=Decimal("7.500"),
        ),
    )
    db.refresh(line)
    assert line.variance == Decimal("-2.500")


def test_knowledge_chunk_search_vector_and_embedding(db: Session) -> None:
    document = _add(
        db,
        KnowledgeDocument(
            doc_type="app_knowledge", title="Plan", content_hash="b" * 64, source_ref="chunks"
        ),
    )
    near = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766
    for index, (content, vector) in enumerate(
        [("Suppliers deliver in packs", near), ("Expiry is tracked per batch", far)]
    ):
        _add(
            db,
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=content,
                token_count=5,
                embedding=vector,
            ),
        )
    matched = (
        db.execute(
            text(
                "SELECT content FROM knowledge_chunks WHERE tsv @@ plainto_tsquery('english', 'packs')"
            )
        )
        .scalars()
        .all()
    )
    assert matched == ["Suppliers deliver in packs"]
    nearest = db.execute(
        select(KnowledgeChunk.content)
        .where(KnowledgeChunk.document_id == document.id)
        .order_by(KnowledgeChunk.embedding.cosine_distance(near))
        .limit(1)
    ).scalar_one()
    assert nearest == "Suppliers deliver in packs"


def test_updated_at_trigger_overrides_whatever_the_client_sends(db: Session) -> None:
    b = _bundle(db)
    db.execute(
        text("UPDATE products SET updated_at = '2000-01-01', name = 'Renamed' WHERE id = :id"),
        {"id": b.product.id},
    )
    stamped = db.execute(
        text("SELECT updated_at > '2020-01-01' FROM products WHERE id = :id"), {"id": b.product.id}
    ).scalar()
    assert stamped is True


@pytest.mark.parametrize("model", [Tenant, User, Supplier, Product])
def test_mutable_tables_have_the_updated_at_trigger(db: Session, model: type) -> None:
    count = db.execute(
        text(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relname = :table AND t.tgname LIKE 'trg_%_set_updated_at'"
        ),
        {"table": model.__tablename__},  # type: ignore[attr-defined]
    ).scalar()
    assert count == 1


def test_defaults_for_a_new_tenant_and_settings(db: Session) -> None:
    tenant = factories.make_tenant(db)
    settings = _add(db, BusinessSettings(tenant_id=tenant.id))
    db.refresh(tenant)
    db.refresh(settings)
    assert (tenant.timezone, tenant.currency, tenant.is_active) == ("Asia/Kolkata", "INR", True)
    assert settings.service_level == Decimal("0.950")
    assert settings.review_period_days == 7
    assert settings.default_lead_time_days == 3
    assert settings.pack_rounding == "up"
    assert settings.censor_policy == "exclude"
    assert settings.priority_weights == {
        "risk": 0.45,
        "value": 0.30,
        "confidence": 0.15,
        "excess": 0.10,
    }


def test_user_email_is_unique_regardless_of_case(db: Session, two_tenants: TwoTenants) -> None:
    factories.make_user(db, two_tenants.a.tenant, email="Owner@Example.com")
    with rejected(db, match="uq_users_email"):
        factories.make_user(db, two_tenants.b.tenant, email="owner@example.COM")


def test_stock_views(db: Session) -> None:
    b = _bundle(db)
    batch = factories.make_batch(
        db, b.tenant, b.product, expiry_date=date(2030, 1, 1), unit_cost=Decimal("8.0000")
    )
    factories.make_balance(
        db, b.tenant, b.product, batch, on_hand=Decimal("5.000"), avg_unit_cost=Decimal("8.0000")
    )
    factories.make_balance(
        db, b.tenant, b.product, None, on_hand=Decimal("3.000"), avg_unit_cost=Decimal("10.0000")
    )

    product_row = db.execute(
        text("SELECT on_hand, stock_value FROM v_product_stock WHERE product_id = :p"),
        {"p": b.product.id},
    ).one()
    assert product_row.on_hand == Decimal("8.000")
    assert product_row.stock_value == Decimal("70.0000000")

    batch_row = db.execute(
        text("SELECT days_to_expiry, on_hand, value FROM v_batch_stock WHERE batch_id = :b"),
        {"b": batch.id},
    ).one()
    today_ist = db.execute(text("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date")).scalar()
    assert batch_row.days_to_expiry == (date(2030, 1, 1) - today_ist).days
    assert batch_row.on_hand == Decimal("5.000")
    assert batch_row.value == Decimal("40.0000000")


def test_views_respect_the_caller_privileges(db: Session) -> None:
    options = (
        db.execute(
            text(
                "SELECT reloptions FROM pg_class WHERE relname IN ('v_product_stock', 'v_batch_stock')"
            )
        )
        .scalars()
        .all()
    )
    assert all("security_invoker=true" in opts for opts in options)
    assert len(options) == 2


def _bundle(db: Session) -> TenantBundle:
    tenant = factories.make_tenant(db)
    category = factories.make_category(db, tenant)
    return TenantBundle(
        tenant=tenant,
        user=factories.make_user(db, tenant),
        category=category,
        product=factories.make_product(db, tenant, category=category),
        supplier=factories.make_supplier(db, tenant),
    )
