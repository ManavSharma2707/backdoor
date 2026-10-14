"""Words and the snapshot of the Monday plan (`report-spec.md`).

Reasons are written from templates, never by a language model: every sentence comes from a
number the engine computed. The snapshot is plain JSON data (strings for money and quantities),
so exports and the report page read the same thing.
"""

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.core.text import humanize_text
from app.engine import dq
from app.engine.backtest import BASELINE_28
from app.engine.calendar import CalendarEvent, delivery_padding, upcoming
from app.engine.constants import FESTIVAL_NOTE_DAYS, FESTIVAL_SECTION_DAYS
from app.engine.event_effects import EffectRecord
from app.engine.plan import Line, PlanResult
from app.engine.selection import Selection

SCHEMA_VERSION = 1
Q3 = Decimal("0.001")
M2 = Decimal("0.01")
RISK_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
CONFIDENCE_LABEL = {"high": "High", "medium": "Fair", "low": "Low"}
RISK_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "none": "None",
}
METHOD_LABEL = {
    "seasonal_naive": "Same weekday last week",
    "moving_average": "Recent average",
    "weekday_profile": "Weekday pattern",
    "ses_weekday": "Smoothed weekday pattern",
    "croston_sba": "Intermittent demand method",
    "lightgbm_global": "Learned model",
    "category_prior": "Category estimate",
}
UNIT_PLURAL = {
    "pcs": ("piece", "pieces"),
    "pack": ("pack", "packs"),
    "strip": ("strip", "strips"),
    "bottle": ("bottle", "bottles"),
    "tube": ("tube", "tubes"),
    "sachet": ("sachet", "sachets"),
    "box": ("box", "boxes"),
    "kg": ("kg", "kg"),
    "litre": ("litre", "litres"),
    "vial": ("vial", "vials"),
    "tin": ("tin", "tins"),
}
WARNING_TEXT = {
    "MISSING_COST": "No purchase price, so the order cannot be costed.",
    "MISSING_SUPPLIER": "No main supplier, so it cannot be ordered from the plan.",
    "MISSING_LEAD_TIME": "No delivery time set, so the default is assumed.",
    "MISSING_EXPIRY": "Stock without a batch or expiry date.",
    "PO_OVERDUE": "An order is late and is not counted as arriving.",
    "CENSORED_HISTORY": "Out of stock for much of the last 8 weeks, so sales understate demand.",
    "WRITE_OFF_NEEDED": "Expired stock is still on the books. Write it off.",
    "MOQ_VS_SHELF_LIFE": "The minimum order is more than it can sell before expiry.",
    "CRITICAL_UNFUNDED": "Likely to run out, and the budget does not cover the order.",
    "PROMO_UPLIFT_UNKNOWN": "A promotion is planned and its effect is not known.",
    "STALE_STOCK_COUNT": "Not counted recently.",
    "ZERO_SALES_UNVERIFIED": "No sales, but it was not on the shelf the whole time.",
    "PRICE_ANOMALY": "The price looks wrong.",
    "NEW_PRODUCT": "New product, the forecast is a first estimate.",
    "SPARSE_HISTORY": "Little sales history.",
    "UNRECORDED_STOCKOUT_SUSPECTED": "Ran out of stock without it being recorded.",
}


def q3(value: float | Decimal) -> str:
    return str(Decimal(repr(round(float(value), 6))).quantize(Q3))


def m2(value: Decimal | float) -> str:
    return str(
        Decimal(value).quantize(M2)
        if isinstance(value, Decimal)
        else Decimal(repr(round(value, 4))).quantize(M2)
    )


def n_text(value: float) -> str:
    """A quantity for a sentence: whole numbers from 10 up, otherwise one decimal when needed."""
    if value >= 10 or abs(value - round(value)) < 0.05:
        return str(round(value))
    return f"{value:.1f}"


def days_text(days: float) -> str:
    """Days of cover for a sentence, with a ceiling so a slow product never says 6663 days."""
    if days > 365:
        return "more than a year"
    return f"about {int(days)} days"


def units(unit: str, qty: float) -> str:
    one, many = UNIT_PLURAL.get(unit, (unit, unit + "s"))
    return one if abs(qty - 1.0) < 1e-9 else many


def with_unit(line: Line, qty: float) -> str:
    return f"{n_text(qty)} {units(line.product.base_unit, qty)}"


def day_text(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


# --------------------------------------------------------------------------- reasons


def reason_sentences(
    line: Line, event_names: Mapping[str, str], nonmoving_days: int = 60
) -> list[str]:
    """The sentences that explain a line, most important first."""
    r = line.replen
    codes = set(line.reason_codes)
    out: list[str] = []
    horizon = r.protection_days
    if "SHORT_FOR_COVER" in codes and line.suggested_qty > 0:
        s = f"Demand for the next {horizon} days is about {with_unit(line, r.demand_protection)}."
        if "FESTIVAL_UPLIFT" in codes and line.event_keys:
            names = ", ".join(event_names.get(k, k) for k in line.event_keys)
            s += f" That includes the effect of {names}."
        out.append(s)
        have = f"You have {n_text(line.on_hand_usable)} on the shelf"
        if line.stock.incoming_confirmed > 0:
            have += f" and {n_text(line.stock.incoming_confirmed)} on the way"
        have += f", and we keep {n_text(r.safety_stock)} as buffer, so you are short by {n_text(r.raw_qty)}."
        out.append(have)
        if line.lead.padding_days:
            out.append(
                f"Deliveries are expected {line.lead.padding_days} "
                f"{'day' if line.lead.padding_days == 1 else 'days'} later because of the festival."
            )
        if "EXPIRY_CAP" in codes:
            out.append(
                "We kept the order small because this stock can only be kept for a limited time."
            )
        if "MOQ_APPLIED" in codes:
            out.append(
                f"The supplier's minimum order is {with_unit(line, float(line.moq_units))}, "
                f"so we suggest {with_unit(line, line.suggested_qty)}."
            )
        elif "PACK_ROUNDING" in codes:
            out.append(
                f"The supplier sells in packs of {n_text(float(line.pack_size))}, "
                f"so we suggest {with_unit(line, line.suggested_qty)}."
            )
        else:
            out.append(f"We suggest {with_unit(line, line.suggested_qty)}.")
    elif line.suggested_qty > 0:
        out.append(f"We suggest {with_unit(line, line.suggested_qty)}.")
    if "OUT_OF_STOCK_NOW" in codes:
        out.append("It is out of stock now.")
    if "BUDGET_LIMITED" in codes:
        out.append(
            f"Your budget covers {with_unit(line, line.allocated_qty)} of the "
            f"{n_text(line.suggested_qty)} suggested."
        )
    if "MISSING_COST" in codes:
        out.append("The purchase price is missing, so this order cannot be costed or ordered yet.")
    if "OVERDUE_ORDER_IGNORED" in codes:
        late = line.stock.overdue[0]
        out.append(
            f"An order of {with_unit(line, late.qty)} is {late.days_late} days late, "
            "so we do not count it."
        )
    if "EXPIRY_LOSS_EXPECTED" in codes:
        out.append(
            f"About {with_unit(line, line.expected_expiry_loss)} may expire before they sell, "
            "so we do not count them."
        )
    if "COVERED" in codes and "SLOW_MOVING" not in codes:
        if line.days_of_cover is not None:
            out.append(
                f"Covered for {days_text(line.days_of_cover)} at the current pace, "
                "so there is no need to order now."
            )
        else:
            out.append(
                "There is stock on the shelf and no sales are expected, so there is no need to order."
            )
    if "NON_MOVING" in codes:
        out.append(f"No sales in the last {nonmoving_days} days although it was on the shelf.")
    if "CHECK_BEFORE_DEAD" in codes:
        out.append(
            f"No sales in the last {nonmoving_days} days, but it was out of stock or off the shelf "
            "for part of that time. Check the stock before calling it dead stock."
        )
    if "SLOW_MOVING" in codes and line.days_of_cover is not None:
        out.append(f"At the current pace this stock lasts {days_text(line.days_of_cover)}.")
    if "EXCESS_STOCK" in codes:
        out.append(
            f"You have about {with_unit(line, line.excess_qty)} more than the next few weeks need."
        )
    if "NEW_PRODUCT" in codes:
        out.append("This product is new, so the forecast is a first estimate.")
    elif "LOW_CONFIDENCE" in codes and line.suggested_qty > 0:
        out.append("We are not sure about this forecast, so check it before you order.")
    likely_short = (
        line.stockout_probability >= 0.30
        and line.suggested_qty > 0
        and line.projected_stockout_date is not None
        and line.projected_stockout_date <= line.lead.arrival
    )
    if likely_short:
        out.append(f"Likely to run out before the next delivery on {day_text(line.lead.arrival)}.")
    return out


def reason_text(line: Line, event_names: Mapping[str, str], nonmoving_days: int = 60) -> str:
    return humanize_text(" ".join(reason_sentences(line, event_names, nonmoving_days)))


# --------------------------------------------------------------------------- lines


@dataclass
class ReportInput:
    tenant_name: str
    business_type: str
    is_synthetic: bool
    as_of: date
    data_cutoff: datetime
    model_version: str
    profile: str
    plan: PlanResult
    events: Sequence[CalendarEvent]
    effects: Sequence[EffectRecord]
    category_names: Mapping[str, str]  # category id (text) to name
    selection: Selection
    findings: Sequence[dq.DqFinding]
    line_ids: Mapping[str, uuid.UUID]
    selection_source: str = "stored"
    notes: list[str] = field(default_factory=list)
    global_model: Mapping[str, Any] = field(default_factory=dict)


def event_name_map(events: Sequence[CalendarEvent]) -> dict[str, str]:
    return {e.event_key: e.name for e in events}


def _supplier(line: Line) -> dict[str, Any] | None:
    s = line.supplier
    return {"id": str(s.id), "code": s.code, "name": s.name} if s else None


def line_payload(
    line: Line, line_id: uuid.UUID, names: Mapping[str, str], as_of: date, nonmoving_days: int
) -> dict[str, Any]:
    p, r = line.product, line.replen
    cost = line.unit_cost
    funded_spend = (
        (Decimal(repr(round(line.allocated_qty, 6))) * cost).quantize(M2) if cost else None
    )
    near = [
        {
            "batch_id": b["batch_id"],
            "batch_no": b["batch_no"],
            "expiry_date": b["expiry_date"].isoformat() if b["expiry_date"] else None,
            "qty": q3(b["qty"]),
            "days_to_expiry": b["days_to_expiry"],
            "exposure_qty": q3(b["exposure_qty"]),
            "exposure_value": m2(b["exposure_value"]),
        }
        for b in line.expiry_batches
    ]
    return {
        "id": str(line_id),
        "product_id": str(p.id),
        "sku": p.sku,
        "name": p.name,
        "category": p.category_name,
        "category_slug": p.category_slug,
        "base_unit": p.base_unit,
        "pack_label": p.pack_label,
        "supplier": _supplier(line),
        "sections": line.sections,
        "risk_level": line.risk_level,
        "risk_label": RISK_LABEL[line.risk_level],
        "confidence": line.confidence,
        "confidence_label": CONFIDENCE_LABEL[line.confidence],
        "forecast_method": line.forecast.method,
        "forecast_method_label": METHOD_LABEL.get(line.forecast.method, line.forecast.method),
        "forecast_error": None if line.wape is None else round(line.wape, 4),
        "demand_class": line.signals.profile.demand_class,
        "demand_7d": q3(line.demand_7d),
        "demand_protection": q3(r.demand_protection),
        "avg_daily_forecast": q3(line.avg_daily_forecast),
        "protection_days": r.protection_days,
        "lead_time_days": line.lead.total_days,
        "lead_time_base_days": line.lead.base_days,
        "lead_time_source": line.lead.source,
        "lead_time_assumed": line.lead.is_assumed,
        "festival_padding_days": line.lead.padding_days,
        "arrival_date": line.lead.arrival.isoformat(),
        "on_hand_total": q3(line.stock.on_hand_total),
        "on_hand_usable": q3(line.on_hand_usable),
        "expected_expiry_loss": q3(line.expected_expiry_loss),
        "expired_qty": q3(line.stock.expired_qty),
        "expired_value": m2(line.stock.expired_value),
        "incoming_confirmed": q3(line.stock.incoming_confirmed),
        "incoming_excluded_overdue": q3(line.stock.incoming_overdue),
        "overdue_orders": [
            {
                "po_number": o.po_number,
                "expected_date": o.expected_date.isoformat(),
                "qty": q3(o.qty),
                "days_late": o.days_late,
            }
            for o in line.stock.overdue
        ],
        "reserved": q3(line.stock.reserved),
        "inventory_position": q3(r.inventory_position),
        "safety_stock": q3(r.safety_stock),
        "target_level": q3(r.target_level),
        "raw_qty": q3(r.raw_qty),
        "moq_units": q3(line.moq_units),
        "pack_size": q3(line.pack_size),
        "suggested_qty": q3(line.suggested_qty),
        "suggested_packs": r.packs,
        "allocated_qty": q3(line.allocated_qty),
        "pack_excess_qty": q3(r.pack_excess_qty),
        "unit_cost": None if cost is None else str(cost.quantize(Decimal("0.0001"))),
        "est_spend": None if line.est_spend is None else m2(line.est_spend),
        "funded_spend": None if funded_spend is None else m2(funded_spend),
        "unfunded_qty": q3(line.unfunded_qty),
        "budget_limited": line.budget_limited,
        "blocked": line.blocked,
        "stockout_probability": round(line.stockout_probability, 3),
        "projected_stockout_date": (
            line.projected_stockout_date.isoformat() if line.projected_stockout_date else None
        ),
        "days_of_cover": None if line.days_of_cover is None else round(line.days_of_cover, 1),
        "stock_status": line.stock_status,
        "days_since_sale": line.days_since_sale,
        "excess_qty": q3(line.excess_qty),
        "excess_value": m2(line.excess_value),
        "expiry_exposure_qty": q3(line.expiry_exposure_qty),
        "expiry_exposure_value": m2(line.expiry_exposure_value),
        "expiry_batches": near,
        "priority_score": line.priority_score,
        "priority_components": line.priority_components,
        "event_keys": line.event_keys,
        "reason_codes": line.reason_codes,
        "reason_text": reason_text(line, names, nonmoving_days),
        "warnings": [{"code": c, "message": WARNING_TEXT.get(c, c)} for c in line.warnings],
        "provenance": line.provenance,
        "sigma_source": line.sigma_source,
        "forecast": {
            "start": as_of.isoformat(),
            "yhat": [round(float(x), 3) for x in line.forecast.yhat],
            "lower": [round(float(x), 3) for x in line.forecast.lower],
            "upper": [round(float(x), 3) for x in line.forecast.upper],
        },
    }


# --------------------------------------------------------------------------- sections


def _supplier_key(line: Line) -> str:
    return line.supplier.name.lower() if line.supplier else "~"


def section_order(lines: Sequence[Line]) -> dict[str, list[Line]]:
    """Lines of each section in the order they are shown."""
    out: dict[str, list[Line]] = {s: [] for s in ("buy", "do_not_buy", "watch", "reduce")}
    for ln in lines:
        for s in ln.sections:
            out[s].append(ln)
    out["buy"].sort(
        key=lambda ln: (
            _supplier_key(ln),
            RISK_RANK[ln.risk_level],
            -float(ln.est_spend or 0),
            ln.product.name,
        )
    )
    out["watch"].sort(
        key=lambda ln: (RISK_RANK[ln.risk_level], -ln.stockout_probability, ln.product.name)
    )
    out["do_not_buy"].sort(
        key=lambda ln: (ln.days_of_cover is None, ln.days_of_cover or 0.0, ln.product.name)
    )
    out["reduce"].sort(
        key=lambda ln: (
            -float(ln.excess_value + ln.expiry_exposure_value + ln.stock.expired_value),
            ln.product.name,
        )
    )
    return out


def _percent(value: float) -> str:
    return f"{round(value * 100)} percent"


def festival_section(ri: ReportInput) -> list[dict[str, Any]]:
    """Events within 35 days: what is learned for each category, with and without the effect."""
    as_of = ri.as_of
    by_event: dict[str, list[EffectRecord]] = {}
    for rec in ri.effects:
        by_event.setdefault(rec.event_key, []).append(rec)
    lines = ri.plan.lines
    out: list[dict[str, Any]] = []
    horizon = ri.plan.lines[0].forecast.yhat.shape[0] if lines else 28
    for event in upcoming(
        [e for e in ri.events if e.kind == "festival"], as_of, FESTIVAL_SECTION_DAYS
    ):
        cats: list[dict[str, Any]] = []
        records = by_event.get(event.event_key, [])
        by_category: dict[str, list[EffectRecord]] = {}
        for rec in records:
            by_category.setdefault(rec.category_key, []).append(rec)
        for category, recs in sorted(
            by_category.items(), key=lambda kv: ri.category_names.get(kv[0], kv[0])
        ):
            best = max(recs, key=lambda x: (x.is_applied, abs(x.multiplier - 1.0)))
            if (
                not best.is_applied
                and abs(best.multiplier - 1.0) < 0.05
                and not best.evidence.get("occurrences")
            ):
                continue
            with_effect, without = _window_totals(lines, category, event, as_of, horizon)
            applied = [x for x in recs if x.is_applied]
            if not applied and not any(abs(x.multiplier - 1.0) >= 0.15 for x in recs):
                continue
            label = best.label
            cats.append(
                {
                    "category": ri.category_names.get(category, category),
                    "multiplier": round(best.multiplier, 3),
                    "windows": {x.window: round(x.multiplier, 3) for x in recs if x.is_applied},
                    "label": label,
                    "label_text": _label_text(best),
                    "n_occurrences": best.n_occurrences,
                    "applied": bool(applied),
                    "evidence": _evidence_text(best, event),
                    "forecast_with_effect": q3(with_effect),
                    "forecast_without_effect": q3(without),
                }
            )
        out.append(
            {
                "event_key": event.event_key,
                "name": event.name,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "pre_window_start": event.anchor.isoformat(),
                "days_away": (event.start - as_of).days,
                "is_verified": event.is_verified,
                "categories": cats,
                "delivery_padding_days": delivery_padding([event], as_of, 14),
            }
        )
    return out


def _label_text(rec: EffectRecord) -> str:
    if not rec.is_applied:
        return "Not enough evidence to adjust the forecast"
    if rec.origin == "configured":
        return "Set by you"
    n = rec.n_occurrences
    return f"Learned from last year, {n} {'occurrence' if n == 1 else 'occurrences'}"


def _evidence_text(rec: EffectRecord, event: CalendarEvent) -> str:
    occ = rec.evidence.get("occurrences", [])
    if not occ:
        return "Set by you." if rec.origin == "configured" else "No past occurrence to learn from."
    ratios = [o["ratio"] for o in occ]
    times = ", ".join(f"{r:.1f}" for r in ratios)
    parts = [
        f"Past sales in this window were {times} times the usual level, across {rec.n_products} products."
    ]
    if rec.consistency is not None:
        parts.append(f"{_percent(rec.consistency)} of the sales volume moved the same way.")
    if not rec.is_applied:
        parts.append("That is not strong enough to change the forecast.")
    return humanize_text(" ".join(parts))


def _window_totals(
    lines: Sequence[Line], category: str, event: CalendarEvent, as_of: date, horizon: int
) -> tuple[float, float]:
    spans = [(first, last) for _, first, last in event.spans()]
    with_effect = without = 0.0
    for ln in lines:
        if str(ln.product.category_id) != category:
            continue
        for d in range(horizon):
            day = as_of + timedelta(days=d)
            if any(a <= day <= b for a, b in spans):
                with_effect += float(ln.forecast.yhat[d])
                without += float(ln.forecast.base[d])
    return with_effect, without


# --------------------------------------------------------------------------- the snapshot


def build_snapshot(ri: ReportInput) -> dict[str, Any]:
    """The report as JSON data, in the shape of `report-spec.md` section 3."""
    plan = ri.plan
    names = event_name_map(ri.events)
    lines = plan.lines
    ordered = section_order(lines)
    ids = ri.line_ids
    line_data = {
        str(ids[ln.key]): line_payload(
            ln, ids[ln.key], names, ri.as_of, plan.settings.nonmoving_days
        )
        for ln in lines
    }
    budget = plan.budget
    settings = plan.settings
    summary_budget = (
        settings.weekly_budget
        if not plan.overrides.override_budget
        else plan.overrides.weekly_budget
    )
    festival = festival_section(ri)
    near_batches = [(ln, b) for ln in lines for b in ln.expiry_batches]
    expiry_batches = [
        {
            "line_id": str(ids[ln.key]),
            "product": ln.product.name,
            "sku": ln.product.sku,
            "batch_no": b["batch_no"],
            "expiry_date": b["expiry_date"].isoformat() if b["expiry_date"] else None,
            "days_to_expiry": b["days_to_expiry"],
            "qty": q3(b["qty"]),
            "exposure_qty": q3(b["exposure_qty"]),
            "exposure_value": m2(b["exposure_value"]),
            "options": _expiry_options(ln, b),
            "status": "near_expiry",
        }
        for ln, b in near_batches
    ]
    for ln in lines:
        for b in ln.stock.expired:
            expiry_batches.append(
                {
                    "line_id": str(ids[ln.key]),
                    "product": ln.product.name,
                    "sku": ln.product.sku,
                    "batch_no": b.batch_no,
                    "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                    "days_to_expiry": None,
                    "qty": q3(b.qty),
                    "exposure_qty": q3(b.qty),
                    "exposure_value": m2(Decimal(repr(round(b.qty, 6))) * b.unit_cost),
                    "options": ["write_off", "return_to_supplier"]
                    if _accepts_returns(ln)
                    else ["write_off"],
                    "status": "expired",
                }
            )
    expiry_batches.sort(key=lambda x: (x["status"] != "expired", -float(x["exposure_value"])))
    dq_notes = dq.summarise(ri.findings)
    confidence_mix = dict(Counter(ln.confidence for ln in lines))
    summary = {
        "planned_spend": m2(budget.funded),
        "needed_spend": m2(budget.needed),
        "budget": None if summary_budget is None else m2(summary_budget),
        "budget_remaining": None
        if summary_budget is None
        else m2(max(summary_budget - budget.funded, Decimal(0))),
        "shortfall": m2(budget.shortfall),
        "lines_buy": len(ordered["buy"]),
        "lines_do_not_buy": len(ordered["do_not_buy"]),
        "lines_watch": len(ordered["watch"]),
        "lines_reduce": len(ordered["reduce"]),
        "critical_count": sum(1 for ln in lines if ln.risk_level == "critical"),
        "high_count": sum(1 for ln in lines if ln.risk_level == "high"),
        "non_moving_value": m2(_stock_value(ln for ln in lines if ln.stock_status == "non_moving")),
        "unverified_value": m2(_stock_value(ln for ln in lines if ln.stock_status == "unverified")),
        "expiry_exposure_value": m2(sum((ln.expiry_exposure_value for ln in lines), Decimal(0))),
        "expired_value": m2(sum((ln.stock.expired_value for ln in lines), Decimal(0))),
        "near_expiry_batches": sum(1 for b in expiry_batches if b["status"] == "near_expiry"),
        "expired_batches": sum(1 for b in expiry_batches if b["status"] == "expired"),
        "dq_errors": sum(n["count"] for n in dq_notes if n["severity"] == "error"),
        "dq_warnings": sum(n["count"] for n in dq_notes if n["severity"] == "warning"),
        "confidence_mix": {k: confidence_mix.get(k, 0) for k in ("high", "medium", "low")},
        "blocked_lines": budget.blocked_lines,
        "festival_note": _festival_note(festival, ri.as_of),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tenant": {
            "name": ri.tenant_name,
            "business_type": ri.business_type,
            "is_synthetic": ri.is_synthetic,
        },
        "week_start": ri.as_of.isoformat(),
        "data_cutoff": ri.data_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": ri.model_version,
        "profile": ri.profile,
        "settings": _settings_snapshot(plan),
        "summary": summary,
        "festival": festival,
        "sections": {s: [str(ids[ln.key]) for ln in ordered[s]] for s in ordered},
        "lines": line_data,
        "expiry_batches": expiry_batches,
        "budget": _budget_view(ri, summary_budget),
        "data_notes": _data_notes(ri, dq_notes),
        "backtest_summary": backtest_summary(ri),
    }


def _stock_value(lines: Any) -> Decimal:
    total = Decimal(0)
    for ln in lines:
        cost = ln.unit_cost if ln.unit_cost is not None else ln.product.avg_cost
        total += Decimal(repr(round(ln.stock.on_hand_sellable, 6))) * cost
    return total


def _accepts_returns(line: Line) -> bool:
    return bool(line.supplier and line.supplier.accepts_expiry_returns)


def _expiry_options(line: Line, batch: dict[str, Any]) -> list[str]:
    options = ["sell_first"]
    if _accepts_returns(line):
        options.append("return_to_supplier")
    options.append("write_off")
    return options


def _settings_snapshot(plan: PlanResult) -> dict[str, Any]:
    s = plan.settings
    return {
        "weekly_budget": None if s.weekly_budget is None else m2(s.weekly_budget),
        "service_level": s.service_level,
        "review_period_days": s.review_period_days,
        "default_lead_time_days": s.default_lead_time_days,
        "near_expiry_days": s.near_expiry_days,
        "nonmoving_days": s.nonmoving_days,
        "slow_cover_days": s.slow_cover_days,
        "excess_horizon_days": s.excess_horizon_days,
        "forecast_horizon_days": s.forecast_horizon_days,
        "backtest_origins": s.backtest_origins,
        "stale_count_days": s.stale_count_days,
        "sellable_shelf_life_fraction": s.sellable_shelf_life_fraction,
        "censor_policy": s.censor_policy,
        "pack_rounding": s.pack_rounding,
        "priority_weights": s.priority_weights,
        "apply_festival_lead_padding": s.apply_festival_lead_padding,
    }


def _festival_note(festival: Sequence[Mapping[str, Any]], as_of: date) -> str | None:
    for f in festival:
        if 0 <= f["days_away"] <= FESTIVAL_NOTE_DAYS or (
            f["days_away"] < 0 <= (date.fromisoformat(f["end"]) - as_of).days
        ):
            if f["days_away"] < 0:
                return humanize_text(f"{f['name']} is on now.")
            return humanize_text(
                f"{f['name']} starts in {f['days_away']} days, on {day_text(date.fromisoformat(f['start']))}."
            )
    return None


def _budget_view(ri: ReportInput, budget_value: Decimal | None) -> dict[str, Any]:
    plan = ri.plan
    b = plan.budget
    ids = ri.line_ids
    w = b.weights
    unfunded = sorted(
        (ln for ln in plan.lines if ln.budget_limited), key=lambda ln: -(ln.priority_score or 0)
    )
    at_risk = [ln for ln in plan.lines if ln.risk_level in ("critical", "high")]
    at_risk.sort(key=lambda ln: (RISK_RANK[ln.risk_level], -ln.stockout_probability))

    def brief(ln: Line) -> dict[str, Any]:
        cost = ln.unit_cost
        return {
            "line_id": str(ids[ln.key]),
            "sku": ln.product.sku,
            "name": ln.product.name,
            "supplier": ln.supplier.name if ln.supplier else None,
            "suggested_qty": q3(ln.suggested_qty),
            "allocated_qty": q3(ln.allocated_qty),
            "unfunded_qty": q3(ln.unfunded_qty),
            "unfunded_value": None
            if cost is None
            else m2(Decimal(repr(round(ln.unfunded_qty, 6))) * cost),
            "risk_level": ln.risk_level,
            "priority_score": ln.priority_score,
            "funded": ln.allocated_qty > 0,
        }

    explanation = humanize_text(
        "Lines are funded in order of a score: the chance of running out counts "
        f"{round(w['risk'] * 100)} percent, expected profit {round(w['value'] * 100)} percent, forecast "
        f"confidence {round(w['confidence'] * 100)} percent, and extra stock takes off "
        f"{round(w['excess'] * 100)} percent. Lines are funded in whole packs."
    )
    return {
        "budget": None if budget_value is None else m2(budget_value),
        "needed": m2(b.needed),
        "funded": m2(b.funded),
        "shortfall": m2(b.shortfall),
        "unfunded_value": m2(b.unfunded_value),
        "unfunded_count": b.unfunded_lines,
        "constrained": b.constrained,
        "unfunded_lines": [brief(ln) for ln in unfunded],
        "still_at_risk": [dict(brief(ln), unfunded=ln.budget_limited) for ln in at_risk],
        "blocked_lines": [brief(ln) for ln in plan.lines if ln.blocked],
        "weights": w,
        "explanation": explanation,
        "claim": (
            "The budget covers the full need."
            if not b.constrained
            else "The budget does not cover the full need. Some demand stays unfunded."
        ),
    }


def _data_notes(ri: ReportInput, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(notes)
    s = ri.plan.settings
    assumed = sum(1 for ln in ri.plan.lines if ln.lead.is_assumed)
    if assumed:
        out.append(
            {
                "code": "ASSUMPTION_LEAD_TIME",
                "severity": "info",
                "count": assumed,
                "entities": [],
                "message": f"{assumed} products use the default delivery time of {s.default_lead_time_days} days.",
                "fix_hint": "Set delivery times on your suppliers.",
            }
        )
    for n in ri.notes:
        out.append(
            {
                "code": "RUN_NOTE",
                "severity": "info",
                "count": 1,
                "entities": [],
                "message": humanize_text(n),
                "fix_hint": None,
            }
        )
    if ri.global_model.get("skipped"):
        out.append(
            {
                "code": "GLOBAL_MODEL_SKIPPED",
                "severity": "info",
                "count": 1,
                "entities": [],
                "message": "The learned model was skipped this week, so the simpler methods made the forecasts.",
                "fix_hint": None,
            }
        )
    return out


def backtest_summary(ri: ReportInput) -> dict[str, Any]:
    sel = ri.selection
    tenant = sel.tenant

    def pick(name: str) -> Any:
        m = tenant.get(name)
        return m

    chosen, base, naive = (
        pick("selected:wape"),
        pick(f"{BASELINE_28}:wape"),
        pick("seasonal_naive:wape"),
    )
    segments = []
    for key, info in sorted(sel.segments.items()):
        score = info.scores.get(info.selected)
        base_score = info.scores.get(BASELINE_28)
        if score is None or not info.valid:
            continue
        segments.append(
            {
                "segment": key,
                "demand_class": info.demand_class,
                "method": info.selected,
                "reason": info.reason,
                "products": info.n_products,
                "points": info.n_points,
                "mae": round(score.mae, 4),
                "wape": None
                if info.demand_class in ("intermittent", "lumpy") or score.wape is None
                else round(score.wape, 4),
                "baseline_mae": None if base_score is None else round(base_score.mae, 4),
            }
        )
    return {
        "tenant_wape": None if chosen is None or chosen.wape is None else round(chosen.wape, 4),
        "bias": None if chosen is None or chosen.bias is None else round(chosen.bias, 4),
        "baseline_wape": None if base is None or base.wape is None else round(base.wape, 4),
        "seasonal_naive_wape": None
        if naive is None or naive.wape is None
        else round(naive.wape, 4),
        "n_origins": sel.n_origins,
        "source": ri.selection_source,
        "by_segment": segments[:60],
    }
