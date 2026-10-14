"""One plan line per product: stock, expiry, replenishment, risk, budget and stock status.

Pure. The pipeline loads the inputs, this module computes every number of the plan, and
`report_builder` turns the result into words and the snapshot.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np

from app.engine import budget as budget_mod
from app.engine.calendar import CalendarEvent, delivery_padding
from app.engine.constants import DAYS_OF_COVER_WINDOW, FORECAST_HORIZON_DAYS
from app.engine.deadstock import excess_quantity, stock_status
from app.engine.demand_class import DemandProfile
from app.engine.expiry import SimBatch, demand_between, simulate_fefo
from app.engine.forecast import ProductForecast
from app.engine.inputs import ProductInfo, SettingsInfo, SupplierInfo
from app.engine.inventory_state import StockState, stock_state
from app.engine.replenishment import (
    LeadTimeResult,
    ReplenishInput,
    ReplenishResult,
    replenish,
    resolve_lead,
    spend,
)
from app.engine.risk import (
    RiskInput,
    classify_risk,
    days_of_cover,
    expected_units_short,
    projected_stockout_date,
    sigma_lead,
    stockout_probability,
)
from app.engine.selection import Selection, confidence_label, sigma_for
from app.engine.types import Confidence, RiskLevel

ZERO = Decimal(0)
SECTIONS = ("buy", "do_not_buy", "watch", "reduce")


@dataclass(frozen=True)
class Overrides:
    """Changes for a what if run. Nothing here is ever written to a plan."""

    weekly_budget: Decimal | None = None
    override_budget: bool = False
    service_level: float | None = None
    review_period_days: int | None = None
    lead_time_delta_by_supplier: Mapping[str, int] = field(default_factory=dict)
    supplier_delay_days: Mapping[str, int] = field(default_factory=dict)
    demand_multiplier: float = 1.0
    excluded_product_ids: frozenset[str] = frozenset()
    forced_include_ids: frozenset[str] = frozenset()

    @property
    def is_empty(self) -> bool:
        return self == Overrides()


@dataclass
class ProductSignals:
    """Facts about the history of a product that the plan needs besides its forecast."""

    profile: DemandProfile
    demand: np.ndarray  # demand per day (sold minus restocked returns), all days
    available: np.ndarray  # True on days the product could be bought
    trusted_share_90: float
    censored_share_56: float
    demand_std_56: float
    start: date
    abc: str = "C"
    promotions_in_horizon: int = 0


@dataclass
class PlanContext:
    as_of: date
    settings: SettingsInfo
    suppliers: Mapping[uuid.UUID, SupplierInfo]
    events: Sequence[CalendarEvent]
    selection: Selection
    horizon: int = FORECAST_HORIZON_DAYS
    in_season: bool = True
    global_model_failed: bool = False
    overrides: Overrides = field(default_factory=Overrides)
    promo_unknown_categories: frozenset[str] = frozenset()


@dataclass
class Line:
    """Everything the plan says about one product. Quantities are floats, money is Decimal."""

    product: ProductInfo
    supplier: SupplierInfo | None
    forecast: ProductForecast
    signals: ProductSignals
    lead: LeadTimeResult
    stock: StockState
    replen: ReplenishResult
    # forecast
    avg_daily_forecast: float = 0.0
    demand_7d: float = 0.0
    demand_lead: float = 0.0
    # stock
    expected_expiry_loss: float = 0.0
    on_hand_usable: float = 0.0
    expiry_batches: list[dict[str, Any]] = field(default_factory=list)
    expiry_exposure_qty: float = 0.0
    expiry_exposure_value: Decimal = ZERO
    # error scale and confidence
    sigma_day: float = 0.0
    sigma_source: str = "assumed"
    confidence: Confidence = "low"
    wape: float | None = None
    # money
    unit_cost: Decimal | None = None
    pack_size: Decimal = Decimal(1)
    moq_units: Decimal = ZERO
    est_spend: Decimal | None = None
    # risk
    stockout_probability: float = 0.0
    projected_stockout_date: date | None = None
    days_of_cover: float | None = None
    risk_level: RiskLevel = "none"
    # status
    stock_status: str = "normal"
    days_since_sale: int | None = None
    excess_qty: float = 0.0
    excess_value: Decimal = ZERO
    # budget
    allocated_qty: float = 0.0
    unfunded_qty: float = 0.0
    budget_limited: bool = False
    blocked: bool = False
    priority_score: float | None = None
    priority_components: dict[str, Any] | None = None
    # tags
    sections: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    event_keys: list[str] = field(default_factory=list)
    expected_short: float = 0.0

    @property
    def key(self) -> str:
        return str(self.product.id)

    @property
    def suggested_qty(self) -> float:
        return self.replen.suggested_qty


@dataclass
class PlanResult:
    lines: list[Line]
    budget: budget_mod.BudgetResult
    settings: SettingsInfo
    overrides: Overrides

    @property
    def by_key(self) -> dict[str, Line]:
        return {ln.key: ln for ln in self.lines}


def _fallback_std(signals: ProductSignals) -> float:
    return signals.demand_std_56


def _downgrades(line: Line, ctx: PlanContext) -> int:
    count = 0
    if line.lead.is_assumed:
        count += 1
    if line.signals.censored_share_56 > 0.30:
        count += 1
    if line.stock.overdue:
        count += 1
    info = line.forecast.interval
    if ctx.global_model_failed and info is not None and info.selected == "lightgbm_global":
        count += 1
    return count


def _scored_error(
    ctx: PlanContext, key: str, forecast: ProductForecast
) -> tuple[float | None, float | None]:
    """WAPE and the scale free MAE of the product, or of its segment when it has few points."""
    own = ctx.selection.products.get(key)
    if own is not None and own.n_points >= 28 and own.method == forecast.method:
        ratio = own.mae / own.mean_actual if own.mean_actual > 0 else None
        return own.wape, ratio
    info = forecast.interval
    if info is not None:
        m = info.scores.get(forecast.method) or info.scores.get(info.selected_stat)
        if m is not None and m.n_points > 0:
            return m.wape, m.mae_ratio
    return None, None


def build_line(
    product: ProductInfo, forecast: ProductForecast, signals: ProductSignals, ctx: PlanContext
) -> Line:
    """All numbers of one product, before the budget is applied."""
    as_of, settings = ctx.as_of, ctx.settings
    ov = ctx.overrides
    supplier = ctx.suppliers.get(product.supplier_id) if product.supplier_id else None
    key = str(product.id)
    yhat = forecast.yhat * ov.demand_multiplier

    term = product.term
    term_days = term.lead_time_days if term else None
    supplier_days = supplier.default_lead_time_days if supplier else None
    shift = ov.lead_time_delta_by_supplier.get(str(supplier.id), 0) if supplier else 0
    delay = ov.supplier_delay_days.get(str(supplier.id), 0) if supplier else 0
    weekdays = supplier.delivery_weekdays if supplier else None
    preliminary = resolve_lead(
        as_of, term_days, supplier_days, settings.default_lead_time_days, weekdays
    )
    padding = (
        delivery_padding(ctx.events, as_of, preliminary.effective_days)
        if settings.apply_festival_lead_padding
        else 0
    )
    lead = resolve_lead(
        as_of, term_days, supplier_days, settings.default_lead_time_days, weekdays, padding
    )
    if shift or delay:
        total = max(lead.total_days + shift + delay, 0)
        lead = replace(lead, total_days=total, arrival=as_of + timedelta(days=total))

    stock = stock_state(product, as_of, lead.arrival)
    if delay and supplier is not None:
        stock.confirmed = [
            replace(a, arrive_on=a.arrive_on + timedelta(days=delay)) for a in stock.confirmed
        ]

    # Expiry: simulate the sellable batches, and the deliveries on the way, against the forecast.
    fraction = settings.sellable_shelf_life_fraction
    shelf = product.shelf_life_days
    sim = [
        SimBatch(
            b.batch_id or f"loose-{i}",
            b.qty,
            b.expiry_date,
            b.unit_cost if b.unit_cost > 0 else product.avg_cost,
            b.batch_no,
        )
        for i, b in enumerate(stock.sellable)
    ]
    for i, a in enumerate(stock.confirmed):
        life = int(shelf * fraction) if (product.is_batch_tracked and shelf) else None
        sim.append(
            SimBatch(
                f"arrival-{i}",
                a.qty,
                a.arrive_on + timedelta(days=life) if life else None,
                product.avg_cost,
                None,
                a.arrive_on,
            )
        )
    fefo = simulate_fefo(sim, yhat, as_of, ctx.horizon)
    existing = fefo.batches[: len(stock.sellable)]
    loss_qty = sum(b.expected_loss for b in existing)
    batches_out: list[dict[str, Any]] = []
    exposure_value = ZERO
    for b in existing:
        near = b.days_to_expiry is not None and b.days_to_expiry <= settings.near_expiry_days
        if near and b.qty > 0:
            exposure_value += b.loss_value
            batches_out.append(
                {
                    "batch_id": b.key if not b.key.startswith("loose-") else None,
                    "batch_no": b.batch_no,
                    "expiry_date": b.expiry_date,
                    "qty": b.qty,
                    "days_to_expiry": b.days_to_expiry,
                    "exposure_qty": b.expected_loss,
                    "exposure_value": b.loss_value,
                    "unit_cost": b.unit_cost,
                }
            )
    near_loss = sum(x["exposure_qty"] for x in batches_out)
    usable = max(stock.on_hand_sellable - loss_qty, 0.0)

    mean_level = float(yhat[:14].mean()) if len(yhat) else 0.0
    sigma, sigma_source = sigma_for(
        key,
        ctx.selection,
        mean_level=mean_level,
        category_key=product.category_slug,
        demand_class=signals.profile.demand_class,
        fallback_std=_fallback_std(signals),
    )
    service = ov.service_level if ov.service_level is not None else settings.service_level
    review = (
        ov.review_period_days if ov.review_period_days is not None else settings.review_period_days
    )
    unit_cost = term.purchase_price if term and term.purchase_price > 0 else None
    pack = term.pack_size if term and term.pack_size > 0 else Decimal(1)
    moq = term.moq_units if term else ZERO

    replen = replenish(
        ReplenishInput(
            forecast=yhat,
            lead_days=lead.total_days,
            review_days=review,
            usable=usable,
            incoming_confirmed=stock.incoming_confirmed,
            incoming_by_arrival=stock.incoming_by(lead.arrival),
            reserved=stock.reserved,
            sigma_day=sigma,
            service_level=service,
            min_stock_qty=product.min_stock_qty,
            pack_size=pack,
            moq_units=moq,
            shelf_life_days=shelf,
            is_batch_tracked=product.is_batch_tracked,
            sellable_fraction=fraction,
            pack_rounding=settings.pack_rounding,
        )
    )
    if key in ov.forced_include_ids and replen.suggested_qty <= 0:
        packs = max(1, int(-(-moq // pack))) if pack > 0 else 1
        replen.packs = packs
        replen.suggested_qty = float(pack * packs)
        replen.reasons.append("FORCED_INCLUDE")

    arrival_stock = usable + stock.incoming_by(lead.arrival) - stock.reserved
    s_lead = sigma_lead(sigma, lead.total_days)
    p_out = stockout_probability(arrival_stock, replen.demand_lead, s_lead)
    stockout_on = projected_stockout_date(usable, stock.confirmed, yhat, as_of, ctx.horizon)
    cover = days_of_cover(usable, yhat)
    avg14 = float(yhat[:DAYS_OF_COVER_WINDOW].mean()) if len(yhat) else 0.0
    risk = classify_risk(
        RiskInput(
            usable=usable,
            avg_forecast=avg14,
            probability=p_out,
            stockout_on=stockout_on,
            arrival=lead.arrival,
            service_level=service,
            order_suggested=replen.suggested_qty > 0,
        )
    )

    d_excess = demand_between(yhat, 0, replen.protection_days + settings.excess_horizon_days)
    excess = excess_quantity(replen.inventory_position, d_excess, replen.safety_stock)
    excess = excess if excess >= 1.0 else 0.0
    status = stock_status(
        demand=signals.demand,
        available=signals.available,
        as_of=as_of,
        start=signals.start,
        age_days=product.age_days(as_of),
        demand_class=signals.profile.demand_class,
        on_hand=stock.on_hand_sellable,
        days_of_cover=cover,
        is_seasonal=product.is_seasonal,
        in_season=ctx.in_season,
        nonmoving_days=settings.nonmoving_days,
        slow_cover_days=settings.slow_cover_days,
    )
    wape, mae_ratio = _scored_error(ctx, key, forecast)
    cost_for_value = unit_cost if unit_cost is not None else product.avg_cost
    line = Line(
        product=product,
        supplier=supplier,
        forecast=forecast,
        signals=signals,
        lead=lead,
        stock=stock,
        replen=replen,
        avg_daily_forecast=replen.demand_protection / max(replen.protection_days, 1),
        demand_7d=float(yhat[:7].sum()),
        demand_lead=replen.demand_lead,
        expected_expiry_loss=loss_qty,
        on_hand_usable=usable,
        expiry_batches=batches_out,
        expiry_exposure_qty=near_loss,
        expiry_exposure_value=exposure_value,
        sigma_day=sigma,
        sigma_source=sigma_source,
        wape=wape,
        unit_cost=unit_cost,
        pack_size=pack,
        moq_units=moq,
        est_spend=spend(replen.suggested_qty, unit_cost),
        stockout_probability=p_out,
        projected_stockout_date=stockout_on,
        days_of_cover=cover,
        risk_level=risk,
        stock_status=status.status,
        days_since_sale=status.days_since_sale,
        excess_qty=excess,
        excess_value=(Decimal(repr(round(excess, 6))) * cost_for_value).quantize(Decimal("0.01")),
        event_keys=sorted({k for k in forecast.event_keys[: replen.protection_days] if k}),
    )
    line.confidence = confidence_label(
        coverage=signals.trusted_share_90,
        wape=wape,
        mae_ratio=mae_ratio,
        demand_class=signals.profile.demand_class,
        censored_share=signals.censored_share_56,
        method=forecast.method,
        downgrades=_downgrades(line, ctx),
    )
    short_supply = usable + stock.incoming_confirmed - stock.reserved
    line.expected_short = expected_units_short(
        short_supply, replen.demand_protection, sigma * (replen.protection_days**0.5)
    )
    return line


def _tag(line: Line, ctx: PlanContext) -> None:
    """Warnings, reason codes, provenance and sections, after the budget is known."""
    p = line.product
    r = line.replen
    warnings = set(line.warnings)
    reasons: list[str] = []
    if p.term is None:
        warnings.add("MISSING_SUPPLIER")
    if line.unit_cost is None:
        warnings.add("MISSING_COST")
        reasons.append("MISSING_COST")
    if line.lead.is_assumed:
        warnings.add("MISSING_LEAD_TIME")
    if line.stock.overdue:
        warnings.add("PO_OVERDUE")
        reasons.append("OVERDUE_ORDER_IGNORED")
    if line.signals.censored_share_56 > 0.30:
        warnings.add("CENSORED_HISTORY")
    if line.stock.expired_qty > 0:
        warnings.add("WRITE_OFF_NEEDED")
    if r.warnings:
        warnings.update(r.warnings)
    if str(p.category_id) in ctx.promo_unknown_categories and line.signals.promotions_in_horizon:
        warnings.add("PROMO_UPLIFT_UNKNOWN")
    if line.stockout_probability >= 0.0 and line.suggested_qty > 0:
        reasons.append("SHORT_FOR_COVER")
    reasons.extend(c for c in r.reasons if c in ("PACK_ROUNDING", "MOQ_APPLIED", "EXPIRY_CAP"))
    if line.event_keys and any(m > 1.0 for m in line.forecast.multiplier[: r.protection_days]):
        reasons.append("FESTIVAL_UPLIFT")
    if line.signals.promotions_in_horizon:
        reasons.append("PROMO_PLANNED")
    if line.expected_expiry_loss > 0:
        reasons.append("EXPIRY_LOSS_EXPECTED")
    if line.budget_limited:
        reasons.append("BUDGET_LIMITED")
        if line.risk_level == "critical":
            warnings.add("CRITICAL_UNFUNDED")
    if line.on_hand_usable <= 0 and line.avg_daily_forecast > 0:
        reasons.append("OUT_OF_STOCK_NOW")
    if line.confidence == "low":
        reasons.append("LOW_CONFIDENCE")
    if line.stock_status == "new":
        reasons.append("NEW_PRODUCT")
    if line.stock_status == "slow":
        reasons.append("SLOW_MOVING")
    if line.stock_status == "non_moving":
        reasons.append("NON_MOVING")
    if line.stock_status == "unverified":
        reasons.append("CHECK_BEFORE_DEAD")
        warnings.add("ZERO_SALES_UNVERIFIED")
    if line.excess_qty > 0:
        reasons.append("EXCESS_STOCK")

    sections: list[str] = []
    covered = line.days_of_cover is not None and line.days_of_cover >= line.lead.total_days
    has_cover = covered or (line.days_of_cover is None and line.on_hand_usable > 0)
    wants = line.suggested_qty > 0
    if wants and (line.allocated_qty > 0 or line.blocked):
        sections.append("buy")
    if not wants and has_cover:
        sections.append("do_not_buy")
        reasons.append("COVERED")
    if (
        line.risk_level in ("critical", "high")
        or "PO_OVERDUE" in warnings
        or (line.confidence == "low" and line.risk_level in ("critical", "high", "medium"))
        or (wants and line.allocated_qty <= 0 and not line.blocked)
    ):
        sections.append("watch")
    if (
        line.stock_status in ("slow", "non_moving", "unverified")
        or line.excess_qty > 0
        or line.expiry_exposure_qty > 0
        or line.stock.expired_qty > 0
    ):
        sections.append("reduce")

    line.warnings = sorted(warnings)
    line.reason_codes = list(dict.fromkeys(reasons))
    line.sections = sections
    external = "assumed" if line.forecast.method == "category_prior" else "calculated"
    line.provenance = {
        "forecast": external,
        "lead_time": "assumed" if line.lead.is_assumed else "observed",
        "sellable_stock": "calculated",
        "on_hand": "observed",
        "incoming": "observed",
        "safety_stock": "assumed" if line.sigma_source == "assumed" else "calculated",
        "suggested": "calculated",
        "unit_cost": "observed" if line.unit_cost is not None else "assumed",
        "pack": "observed" if p.term else "assumed",
        "effect": "calculated",
    }


def build_plan(
    products: Sequence[ProductInfo],
    forecasts: Sequence[ProductForecast],
    signals: Sequence[ProductSignals],
    ctx: PlanContext,
    extra_warnings: Mapping[str, Sequence[str]] | None = None,
) -> PlanResult:
    """Lines for every active product, then the budget over all of them."""
    lines: list[Line] = []
    skip = ctx.overrides.excluded_product_ids
    for product, fc, sig in zip(products, forecasts, signals, strict=True):
        if not product.is_active or str(product.id) in skip:
            continue
        line = build_line(product, fc, sig, ctx)
        line.warnings = list(extra_warnings.get(line.key, ())) if extra_warnings else []
        lines.append(line)

    budget_value = (
        ctx.overrides.weekly_budget if ctx.overrides.override_budget else ctx.settings.weekly_budget
    )
    wanting = []
    for ln in lines:
        packs = ln.replen.packs
        if packs <= 0:
            continue
        cost = ln.unit_cost
        margin = (
            float(
                (ln.product.selling_price - cost)
                * Decimal(repr(round(min(ln.replen.demand_protection, ln.suggested_qty), 6)))
            )
            if cost is not None
            else 0.0
        )
        excess = min(
            max(
                (ln.replen.pack_excess_qty + ln.expiry_exposure_qty) / max(ln.suggested_qty, 1.0),
                0.0,
            ),
            1.0,
        )
        wanting.append(
            budget_mod.BudgetLine(
                ln.key,
                packs,
                ln.pack_size,
                ln.moq_units,
                cost,
                ln.stockout_probability,
                margin,
                ln.confidence,
                excess,
                ln.risk_level == "critical",
            )
        )
    result = budget_mod.allocate(wanting, budget_value, ctx.settings.priority_weights)
    for ln in lines:
        a = result.allocations.get(ln.key)
        if a is None:
            ln.allocated_qty = 0.0
            continue
        ln.allocated_qty = float(a.qty)
        ln.unfunded_qty = ln.suggested_qty - ln.allocated_qty
        ln.budget_limited = a.budget_limited
        ln.blocked = a.blocked
        ln.priority_score = a.score
        ln.priority_components = a.components or None
        if cost := ln.unit_cost:
            ln.est_spend = spend(ln.suggested_qty, cost)
    for ln in lines:
        _tag(ln, ctx)
    return PlanResult(lines, result, ctx.settings, ctx.overrides)


def plan_metrics(plan: PlanResult) -> dict[str, Any]:
    """Headline numbers of a plan, used by what if runs to compare scenarios."""
    lines = plan.lines
    funded = plan.budget.funded
    return {
        "planned_spend": funded,
        "needed": plan.budget.needed,
        "shortfall": plan.budget.shortfall,
        "critical_lines": sum(1 for ln in lines if ln.risk_level == "critical"),
        "high_lines": sum(1 for ln in lines if ln.risk_level == "high"),
        "expected_units_short": round(sum(_short_after_funding(ln) for ln in lines), 3),
        "expiry_exposure_value": sum((ln.expiry_exposure_value for ln in lines), ZERO),
        "unfunded_value": plan.budget.unfunded_value,
        "buy_lines": sum(1 for ln in lines if "buy" in ln.sections),
    }


def _short_after_funding(ln: Line) -> float:
    supply = ln.on_hand_usable + ln.stock.incoming_confirmed - ln.stock.reserved + ln.allocated_qty
    sigma = ln.sigma_day * (ln.replen.protection_days**0.5)
    return expected_units_short(supply, ln.replen.demand_protection, sigma)
