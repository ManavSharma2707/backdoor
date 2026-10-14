"""Data quality checks (`engine-spec.md` section 14). Pure: records in, findings out.

Each finding names the thing that is wrong in plain words and what to do about it. Findings
never block the plan. They are shown on the lines they concern and in the "Data and confidence
notes" section.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.engine.calendar import CalendarEvent
from app.engine.constants import (
    CALENDAR_LOOKAHEAD_DAYS,
    CENSORED_SHARE_WARN,
    MIN_TRUSTED_DAYS,
    PRICE_ANOMALY_RATIO,
    UNRECORDED_STOCKOUT_DAYS,
)
from app.engine.inputs import ProductInfo, SettingsInfo, SupplierInfo
from app.engine.lead_time import resolve_lead_time

CODES = (
    "MISSING_LEAD_TIME",
    "MISSING_COST",
    "MISSING_SUPPLIER",
    "MISSING_EXPIRY",
    "STALE_STOCK_COUNT",
    "NEGATIVE_STOCK",
    "BATCH_QTY_MISMATCH",
    "RECEIPT_EXCEEDS_ORDER",
    "PO_OVERDUE",
    "SPARSE_HISTORY",
    "NEW_PRODUCT",
    "CENSORED_HISTORY",
    "UNRECORDED_STOCKOUT_SUSPECTED",
    "DUPLICATE_SALE_SUSPECT",
    "PRICE_ANOMALY",
    "ZERO_SALES_UNVERIFIED",
    "CALENDAR_STALE",
    "PROMO_UPLIFT_UNKNOWN",
    "MOQ_VS_SHELF_LIFE",
)
SEVERITIES = {
    "MISSING_LEAD_TIME": "warning",
    "MISSING_COST": "error",
    "MISSING_SUPPLIER": "error",
    "MISSING_EXPIRY": "error",
    "STALE_STOCK_COUNT": "warning",
    "NEGATIVE_STOCK": "error",
    "BATCH_QTY_MISMATCH": "error",
    "RECEIPT_EXCEEDS_ORDER": "warning",
    "PO_OVERDUE": "warning",
    "SPARSE_HISTORY": "info",
    "NEW_PRODUCT": "info",
    "CENSORED_HISTORY": "warning",
    "UNRECORDED_STOCKOUT_SUSPECTED": "info",
    "DUPLICATE_SALE_SUSPECT": "info",
    "PRICE_ANOMALY": "warning",
    "ZERO_SALES_UNVERIFIED": "info",
    "CALENDAR_STALE": "warning",
    "PROMO_UPLIFT_UNKNOWN": "info",
    "MOQ_VS_SHELF_LIFE": "warning",
}


@dataclass(frozen=True)
class DqFinding:
    code: str
    severity: str
    message: str
    fix_hint: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    entity_label: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def finding(
    code: str,
    message: str,
    fix_hint: str | None = None,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    detail: dict[str, Any] | None = None,
) -> DqFinding:
    return DqFinding(
        code,
        SEVERITIES[code],
        message,
        fix_hint,
        entity_type,
        entity_id,
        entity_label,
        detail or {},
    )


def _product(
    code: str,
    product: ProductInfo,
    message: str,
    hint: str | None,
    detail: dict[str, Any] | None = None,
) -> DqFinding:
    return finding(
        code,
        message,
        hint,
        entity_type="product",
        entity_id=product.id,
        entity_label=f"{product.name} ({product.sku})",
        detail=detail,
    )


# --------------------------------------------------------------------------- catalogue


def check_catalogue(
    products: Sequence[ProductInfo],
    suppliers: Mapping[uuid.UUID, SupplierInfo],
    settings: SettingsInfo,
    abc: Mapping[uuid.UUID, str],
    as_of: date,
) -> list[DqFinding]:
    """Supplier, cost, lead time, expiry, count and price checks on the active products."""
    out: list[DqFinding] = []
    for p in products:
        if not p.is_active:
            continue
        if p.term is None:
            out.append(
                _product(
                    "MISSING_SUPPLIER",
                    p,
                    f"{p.name} has no main supplier, so it cannot be ordered from the plan.",
                    "Add a supplier price for this product.",
                )
            )
            out.append(
                _product(
                    "MISSING_COST",
                    p,
                    f"{p.name} has no purchase price, so its order cannot be costed.",
                    "Add the purchase price from your supplier.",
                )
            )
        elif p.term.purchase_price <= 0:
            out.append(
                _product(
                    "MISSING_COST",
                    p,
                    f"{p.name} has no purchase price, so its order cannot be costed.",
                    "Add the purchase price from your supplier.",
                )
            )
        supplier_id = p.supplier_id
        supplier = suppliers.get(supplier_id) if supplier_id else None
        lead = resolve_lead_time(
            p.term.lead_time_days if p.term else None,
            supplier.default_lead_time_days if supplier else None,
            settings.default_lead_time_days,
        )
        if lead.is_assumed:
            out.append(
                _product(
                    "MISSING_LEAD_TIME",
                    p,
                    f"No delivery time is set for {p.name}, so we assume "
                    f"{settings.default_lead_time_days} days.",
                    "Set the delivery time on the supplier or on this product's supplier price.",
                    {"assumed_days": settings.default_lead_time_days},
                )
            )
        if p.is_batch_tracked:
            loose = sum(b.qty for b in p.batches if b.batch_id is None)
            if loose > 0:
                out.append(
                    _product(
                        "MISSING_EXPIRY",
                        p,
                        f"{p.name} has stock with no batch or expiry date, so expiry cannot be checked.",
                        "Count the stock and record its batch and expiry date.",
                        {"qty": round(loose, 3)},
                    )
                )
        if abc.get(p.id) == "A":
            limit = as_of - timedelta(days=settings.stale_count_days)
            if p.last_count_date is None or p.last_count_date < limit:
                since = (
                    f"{(as_of - p.last_count_date).days} days ago" if p.last_count_date else "never"
                )
                out.append(
                    _product(
                        "STALE_STOCK_COUNT",
                        p,
                        f"{p.name} is one of your top sellers and was last counted {since}.",
                        "Count this product and post the count.",
                        {
                            "last_count_date": p.last_count_date.isoformat()
                            if p.last_count_date
                            else None
                        },
                    )
                )
        if p.term and p.term.purchase_price > 0 and p.selling_price < p.term.purchase_price:
            out.append(
                _product(
                    "PRICE_ANOMALY",
                    p,
                    f"{p.name} sells for less than it costs to buy.",
                    "Check the selling price and the purchase price.",
                    {"kind": "selling_below_cost"},
                )
            )
        if p.term and p.previous_term_prices:
            previous = p.previous_term_prices[0]
            if previous > 0:
                change = abs(p.term.purchase_price - previous) / previous
                if change > Decimal(str(PRICE_ANOMALY_RATIO)):
                    out.append(
                        _product(
                            "PRICE_ANOMALY",
                            p,
                            f"The purchase price of {p.name} changed by "
                            f"{round(float(change) * 100)} percent.",
                            "Check that the new price is right.",
                            {"kind": "price_jump", "change": round(float(change), 3)},
                        )
                    )
        age = p.age_days(as_of)
        if age < settings.nonmoving_days:
            out.append(
                _product(
                    "NEW_PRODUCT",
                    p,
                    f"{p.name} is new, so its forecast is only a first estimate.",
                    None,
                    {"age_days": age},
                )
            )
    return out


# --------------------------------------------------------------------------- stock and history


@dataclass(frozen=True)
class StockIssue:
    product_id: uuid.UUID
    batch_id: uuid.UUID | None
    on_hand: float
    ledger: float | None = None


def check_stock(
    negatives: Iterable[StockIssue],
    mismatches: Iterable[StockIssue],
    labels: Mapping[uuid.UUID, str],
) -> list[DqFinding]:
    out: list[DqFinding] = []
    for row in negatives:
        out.append(
            finding(
                "NEGATIVE_STOCK",
                f"{labels.get(row.product_id, 'A product')} shows less than zero in stock.",
                "Count the stock and post the count.",
                entity_type="product",
                entity_id=row.product_id,
                entity_label=labels.get(row.product_id),
                detail={"on_hand": row.on_hand},
            )
        )
    seen: set[uuid.UUID] = set()
    for row in mismatches:
        if row.product_id in seen:
            continue
        seen.add(row.product_id)
        out.append(
            finding(
                "BATCH_QTY_MISMATCH",
                f"The stock shown for {labels.get(row.product_id, 'a product')} does not match its "
                "movements.",
                "Run the stock check from the inventory page and contact support if it stays.",
                entity_type="product",
                entity_id=row.product_id,
                entity_label=labels.get(row.product_id),
                detail={"on_hand": row.on_hand, "ledger": row.ledger},
            )
        )
    return out


@dataclass(frozen=True)
class HistoryFacts:
    trusted_days: int
    censored_share: float


def check_history(
    products: Sequence[ProductInfo],
    facts: Mapping[uuid.UUID, HistoryFacts],
    as_of: date,
    nonmoving_days: int,
) -> list[DqFinding]:
    out: list[DqFinding] = []
    for p in products:
        if not p.is_active:
            continue
        h = facts.get(p.id)
        if h is None:
            continue
        if h.trusted_days < MIN_TRUSTED_DAYS and p.age_days(as_of) >= nonmoving_days:
            out.append(
                _product(
                    "SPARSE_HISTORY",
                    p,
                    f"{p.name} has only {h.trusted_days} days of trusted sales history.",
                    "Keep recording sales and stock. The forecast improves with more days.",
                    {"trusted_days": h.trusted_days},
                )
            )
        if h.censored_share > CENSORED_SHARE_WARN:
            out.append(
                _product(
                    "CENSORED_HISTORY",
                    p,
                    f"{p.name} was out of stock on {round(h.censored_share * 100)} percent of the last "
                    "8 weeks, so sales understate demand.",
                    "Record out of stock periods and keep it stocked.",
                    {"censored_share": round(h.censored_share, 3)},
                )
            )
    return out


@dataclass(frozen=True)
class InferredStockout:
    product_id: uuid.UUID
    start: date
    end: date | None
    covered_by_recorded: bool


def check_unrecorded_stockouts(
    rows: Iterable[InferredStockout],
    labels: Mapping[uuid.UUID, str],
    as_of: date,
    recent_days: int = 90,
) -> list[DqFinding]:
    """Zero stock stretches of more than two days that the owner never recorded."""
    out: list[DqFinding] = []
    best: dict[uuid.UUID, InferredStockout] = {}
    limit = as_of - timedelta(days=recent_days)
    for row in rows:
        if row.covered_by_recorded:
            continue
        end = row.end or (as_of - timedelta(days=1))
        if (end - row.start).days + 1 <= UNRECORDED_STOCKOUT_DAYS or end < limit:
            continue
        prior = best.get(row.product_id)
        if prior is None or row.start > prior.start:
            best[row.product_id] = row
    for pid, row in sorted(best.items(), key=lambda kv: str(kv[0])):
        name = labels.get(pid, "A product")
        out.append(
            finding(
                "UNRECORDED_STOCKOUT_SUSPECTED",
                f"{name} had no stock from {row.start.isoformat()} and nobody recorded it as out of stock.",
                "Record the out of stock period so those days are not counted as low demand.",
                entity_type="product",
                entity_id=pid,
                entity_label=name,
                detail={
                    "start": row.start.isoformat(),
                    "end": row.end.isoformat() if row.end else None,
                },
            )
        )
    return out


# --------------------------------------------------------------------------- purchasing


@dataclass(frozen=True)
class OverduePo:
    po_id: uuid.UUID
    po_number: str
    supplier_name: str
    expected_date: date
    days_late: int


@dataclass(frozen=True)
class ExceptionReceipts:
    supplier_id: uuid.UUID
    supplier_name: str
    count: int


def check_purchasing(
    overdue: Iterable[OverduePo], exceptions: Iterable[ExceptionReceipts]
) -> list[DqFinding]:
    out: list[DqFinding] = []
    for po in overdue:
        out.append(
            finding(
                "PO_OVERDUE",
                f"Order {po.po_number} to {po.supplier_name} is {po.days_late} days late. "
                "We do not count its stock as arriving.",
                "Call the supplier, then receive the goods or cancel the order.",
                entity_type="purchase_order",
                entity_id=po.po_id,
                entity_label=po.po_number,
                detail={"expected_date": po.expected_date.isoformat(), "days_late": po.days_late},
            )
        )
    for ex in exceptions:
        out.append(
            finding(
                "RECEIPT_EXCEEDS_ORDER",
                f"{ex.count} goods receipts from {ex.supplier_name} in the last 30 days were "
                "recorded as exceptions.",
                "Check those receipts match what was ordered.",
                entity_type="supplier",
                entity_id=ex.supplier_id,
                entity_label=ex.supplier_name,
                detail={"count": ex.count},
            )
        )
    return out


@dataclass(frozen=True)
class DuplicateBill:
    sale_id: uuid.UUID
    bill_no: str
    other_bill_no: str


def check_duplicate_sales(rows: Iterable[DuplicateBill]) -> list[DqFinding]:
    return [
        finding(
            "DUPLICATE_SALE_SUSPECT",
            f"Bill {row.bill_no} has the same items and total as bill {row.other_bill_no}, "
            "saved within two minutes.",
            "Void one of them if it was entered twice.",
            entity_type="sale",
            entity_id=row.sale_id,
            entity_label=row.bill_no,
        )
        for row in rows
    ]


def check_calendar(events: Iterable[CalendarEvent], as_of: date) -> list[DqFinding]:
    """Warn when no event starts or runs in the next 60 days."""
    horizon = as_of + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    if any(e.end >= as_of and e.start <= horizon for e in events):
        return []
    return [
        finding(
            "CALENDAR_STALE",
            "The festival calendar has no event in the next 60 days, so no festival effect is planned.",
            "Add the coming festivals in Settings, Calendar.",
        )
    ]


# --------------------------------------------------------------------------- summaries


def summarise(findings: Iterable[DqFinding]) -> list[dict[str, Any]]:
    """One note per code for the report: count, severity, message and the entities involved."""
    groups: dict[str, list[DqFinding]] = defaultdict(list)
    for f in findings:
        groups[f.code].append(f)
    order = {"error": 0, "warning": 1, "info": 2}
    notes: list[dict[str, Any]] = []
    for code, items in groups.items():
        first = items[0]
        notes.append(
            {
                "code": code,
                "severity": first.severity,
                "message": first.message if len(items) == 1 else _plural(code, len(items), first),
                "fix_hint": first.fix_hint,
                "count": len(items),
                "entities": [
                    {
                        "type": f.entity_type,
                        "id": str(f.entity_id) if f.entity_id else None,
                        "label": f.entity_label,
                    }
                    for f in sorted(items, key=lambda f: f.entity_label or "")[:25]
                ],
            }
        )
    notes.sort(key=lambda n: (order[n["severity"]], n["code"]))
    return notes


_PLURAL = {
    "MISSING_SUPPLIER": "{n} products have no main supplier, so they cannot be ordered from the plan.",
    "MISSING_COST": "{n} products have no purchase price, so their orders cannot be costed.",
    "MISSING_LEAD_TIME": "{n} products have no delivery time set, so we assume the business default.",
    "MISSING_EXPIRY": "{n} products have stock with no batch or expiry date.",
    "STALE_STOCK_COUNT": "{n} of your top sellers have not been counted recently.",
    "CENSORED_HISTORY": "{n} products were out of stock for much of the last 8 weeks.",
    "SPARSE_HISTORY": "{n} products have little sales history.",
    "NEW_PRODUCT": "{n} products are new, so their forecasts are first estimates.",
    "PO_OVERDUE": "{n} purchase orders are late. We do not count their stock as arriving.",
    "UNRECORDED_STOCKOUT_SUSPECTED": "{n} products ran out of stock without it being recorded.",
    "PRICE_ANOMALY": "{n} products have a suspicious price.",
    "ZERO_SALES_UNVERIFIED": "{n} products had no sales but also little time on the shelf. Check "
    "them before calling them dead stock.",
    "PROMO_UPLIFT_UNKNOWN": "{n} products have a promotion planned and we have no history to "
    "estimate its effect.",
    "MOQ_VS_SHELF_LIFE": "{n} products have a minimum order larger than they can sell before expiry.",
    "NEGATIVE_STOCK": "{n} products show less than zero in stock.",
    "BATCH_QTY_MISMATCH": "{n} products have stock that does not match their movements.",
    "RECEIPT_EXCEEDS_ORDER": "{n} suppliers have exception receipts in the last 30 days.",
    "DUPLICATE_SALE_SUSPECT": "{n} bills look like duplicates.",
}


def _plural(code: str, n: int, first: DqFinding) -> str:
    template = _PLURAL.get(code)
    return template.format(n=n) if template else f"{first.message} ({n} cases)"
