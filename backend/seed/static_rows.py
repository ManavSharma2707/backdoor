"""Rows for the catalogue-side tables: categories, products, prices, suppliers, terms, promotions,
and the true demand table. Built from the catalogue, timelines and plan, in `COLUMNS` order."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from seed.demand import Demand
from seed.model import (
    K_CATEGORY,
    K_PRICE,
    K_PROMO,
    K_SUPPLIER,
    K_TERM,
    UTC,
    Catalog,
    cost4,
    make_uuid,
    money,
    tenant_uuid,
)
from seed.pricing import Timelines
from seed.scenarios import ScenarioPlan

CREATED = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
SEED_CREATED = datetime(2025, 4, 13, 2, 0, tzinfo=UTC)


def tenant_row(catalog: Catalog) -> tuple[Any, ...]:
    p = catalog.profile
    return (
        tenant_uuid(p),
        p.slug,
        p.name,
        p.business_type,
        p.key,
        "Asia/Kolkata",
        "INR",
        True,
        True,
        CREATED,
        CREATED,
    )


def category_rows(catalog: Catalog) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    return [
        (make_uuid(ti, K_CATEGORY, i + 1), tenant, c["name"], c["slug"], c["position"], True)
        for i, c in enumerate(catalog.categories)
    ]


def product_rows(catalog: Catalog, tax_ids: dict[str, Any]) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    rows = []
    for p in catalog.products:
        rows.append(
            (
                make_uuid(ti, 4, p.index + 1),
                tenant,
                p.sku,
                p.barcode,
                p.name,
                p.brand,
                make_uuid(ti, K_CATEGORY, p.category_index + 1),
                p.base_unit,
                p.pack_label,
                tax_ids[p.tax],
                money(p.mrp),
                money(p.selling_price),
                p.is_batch_tracked,
                p.shelf_life_days,
                p.schedule_class,
                p.generic_name,
                p.strength,
                p.dosage_form,
                p.manufacturer,
                p.min_stock_qty,
                p.is_seasonal,
                p.launched_on,
                True,
                None,
                SEED_CREATED,
                SEED_CREATED,
            )
        )
    return rows


def supplier_rows(catalog: Catalog) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    rows = []
    for s in catalog.suppliers:
        rows.append(
            (
                make_uuid(ti, K_SUPPLIER, s.index + 1),
                tenant,
                s.code,
                s.name,
                s.contact_name,
                s.payment_terms_days,
                s.default_lead_time_days,
                s.delivery_weekdays,
                money(s.min_order_value) if s.min_order_value else None,
                money(s.credit_limit) if s.credit_limit else None,
                s.accepts_expiry_returns,
                s.expiry_return_window_days,
                s.return_window_days,
                True,
                None,
                SEED_CREATED,
                SEED_CREATED,
            )
        )
    return rows


def _segments(values: np.ndarray) -> list[tuple[int, int]]:
    """Runs of equal values as (start, end) index pairs."""
    change = np.nonzero(np.diff(values) != 0)[0] + 1
    starts = [0, *[int(c) for c in change]]
    ends = [*[s - 1 for s in starts[1:]], len(values) - 1]
    return list(zip(starts, ends, strict=True))


def price_rows(catalog: Catalog, tl: Timelines, plan: ScenarioPlan) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    rows: list[tuple[Any, ...]] = []
    n = 0
    for p in catalog.products:
        key = tl.mrp[p.index, :].astype(np.int64) * 10_000_000 + tl.sell[p.index, :]
        key = key * 4_000 + (tl.promo[p.index, :].astype(np.int64) + 1)
        segs = _segments(key)
        for _k, (a, b) in enumerate(segs):
            n += 1
            if a == 0:
                reason = "Opening price"
            elif tl.promo[p.index, a] >= 0:
                reason = "Promotion"
            elif tl.promo[p.index, a - 1] >= 0:
                reason = "Promotion ended"
            else:
                reason = "Price change"
            start = plan.start + timedelta(days=a) if a > 0 else plan.start - timedelta(days=1)
            end = plan.start + timedelta(days=b) if b < plan.n_days - 1 else None
            rows.append(
                (
                    make_uuid(ti, K_PRICE, n),
                    tenant,
                    make_uuid(ti, 4, p.index + 1),
                    money(int(tl.mrp[p.index, a])),
                    money(int(tl.sell[p.index, a])),
                    start,
                    end,
                    reason,
                )
            )
    return rows


def term_rows(catalog: Catalog, tl: Timelines, plan: ScenarioPlan) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    rows: list[tuple[Any, ...]] = []
    n = 0
    for p in catalog.products:
        if not p.has_term:
            continue
        for a, b in _segments(tl.cost[p.index, :]):
            n += 1
            start = plan.start + timedelta(days=a) if a > 0 else plan.start - timedelta(days=1)
            end = plan.start + timedelta(days=b) if b < plan.n_days - 1 else None
            rows.append(
                (
                    make_uuid(ti, K_TERM, n),
                    tenant,
                    make_uuid(ti, K_SUPPLIER, p.supplier + 1),
                    make_uuid(ti, 4, p.index + 1),
                    True,
                    cost4(int(tl.cost[p.index, a])),
                    p.pack_size,
                    p.moq_units,
                    p.term_lead_time_days,
                    start,
                    end,
                    SEED_CREATED,
                )
            )
    return rows


def promotion_rows(catalog: Catalog, tl: Timelines, plan: ScenarioPlan) -> list[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    slugs = catalog.category_slugs()
    rows = []
    for promo in tl.promotions:
        cat_id = (
            make_uuid(ti, K_CATEGORY, slugs.index(promo.category) + 1) if promo.category else None
        )
        prod_id = make_uuid(ti, 4, promo.product + 1) if promo.product is not None else None
        rows.append(
            (
                make_uuid(ti, K_PROMO, promo.index + 1),
                tenant,
                promo.name,
                promo.kind,
                prod_id,
                cat_id,
                f"{promo.discount_pct:.2f}",
                plan.start + timedelta(days=promo.start_idx),
                plan.start + timedelta(days=promo.end_idx),
                SEED_CREATED,
            )
        )
    return rows


def true_demand_rows(catalog: Catalog, demand: Demand) -> Iterator[tuple[Any, ...]]:
    ti, tenant = catalog.profile.index, tenant_uuid(catalog.profile)
    dates: list[date] = demand.dates
    for p in catalog.products:
        pid = make_uuid(ti, 4, p.index + 1)
        td, ev, pm = (
            demand.true_demand[p.index],
            demand.event_mult[p.index],
            demand.promo_mult[p.index],
        )
        for t, d in enumerate(dates):
            yield (tenant, pid, d, int(td[t]), f"{float(ev[t]):.3f}", f"{float(pm[t]):.3f}")
