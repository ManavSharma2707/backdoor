"""CSV exports (`report-spec.md` section 6): UTF-8 with a BOM so Excel reads the text properly."""

import csv
import io
from decimal import Decimal

from app.services.export.common import PAISA, ExportData, ExportLine, dec, text_safe

PURCHASE_COLUMNS = (
    "supplier_code",
    "supplier_name",
    "sku",
    "product_name",
    "pack_size",
    "packs",
    "quantity",
    "unit_cost",
    "line_total",
    "expected_delivery_date",
    "decision",
    "reason",
)
PLAN_COLUMNS = (
    "sku",
    "product_name",
    "category",
    "supplier_code",
    "supplier_name",
    "sections",
    "risk_level",
    "confidence",
    "forecast_method",
    "demand_class",
    "protection_days",
    "lead_time_days",
    "lead_time_source",
    "arrival_date",
    "avg_daily_forecast",
    "demand_7d",
    "demand_protection",
    "on_hand_total",
    "on_hand_usable",
    "expected_expiry_loss",
    "incoming_confirmed",
    "incoming_excluded_overdue",
    "reserved",
    "inventory_position",
    "safety_stock",
    "target_level",
    "raw_qty",
    "moq_units",
    "pack_size",
    "suggested_qty",
    "allocated_qty",
    "pack_excess_qty",
    "unit_cost",
    "est_spend",
    "funded_spend",
    "unfunded_qty",
    "budget_limited",
    "stockout_probability",
    "projected_stockout_date",
    "days_of_cover",
    "stock_status",
    "excess_qty",
    "excess_value",
    "expiry_exposure_qty",
    "expiry_exposure_value",
    "priority_score",
    "reason_codes",
    "reason_text",
    "warnings",
    "decision",
    "final_qty",
)


def _quantity(line: ExportLine) -> Decimal:
    return (
        line.final_qty
        if line.final_qty is not None and line.decision != "pending"
        else line.funded_qty
    )


def purchase_rows(data: ExportData) -> list[list[str]]:
    rows = []
    for ln in data.purchase_lines():
        d = ln.data
        supplier = d["supplier"]
        qty = _quantity(ln)
        pack = dec(d["pack_size"]) or Decimal(1)
        cost = ln.unit_cost or Decimal(0)
        packs = (qty / pack).quantize(Decimal("0.001")) if pack else qty
        rows.append(
            [
                text_safe(supplier["code"]),
                text_safe(supplier["name"]),
                text_safe(d["sku"]),
                text_safe(d["name"]),
                f"{pack:f}",
                f"{packs:f}",
                f"{qty:f}",
                f"{cost:f}",
                f"{(qty * cost).quantize(PAISA):f}",
                d["arrival_date"],
                ln.decision,
                text_safe(ln.reason or d["reason_text"]),
            ]
        )
    rows.sort(key=lambda r: (r[1].lower(), r[3].lower()))
    return rows


def plan_rows(data: ExportData) -> list[list[str]]:
    rows = []
    for ln in data.lines:
        d = ln.data
        if not data._wanted(ln):
            continue
        supplier = d.get("supplier") or {}
        values = {
            **{k: d.get(k) for k in PLAN_COLUMNS},
            "product_name": d["name"],
            "supplier_code": supplier.get("code"),
            "supplier_name": supplier.get("name"),
            "sections": "|".join(d["sections"]),
            "reason_codes": "|".join(d["reason_codes"]),
            "warnings": "|".join(w["code"] for w in d["warnings"]),
            "decision": ln.decision,
            "final_qty": None if ln.final_qty is None else f"{ln.final_qty:f}",
        }
        rows.append([_cell(values[c]) for c in PLAN_COLUMNS])
    rows.sort(key=lambda r: r[1].lower())
    return rows


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return text_safe(str(value))


def build_csv(data: ExportData, kind: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    if kind == "plan_lines":
        writer.writerow(PLAN_COLUMNS)
        writer.writerows(plan_rows(data))
    else:
        writer.writerow(PURCHASE_COLUMNS)
        writer.writerows(purchase_rows(data))
    return buffer.getvalue().encode("utf-8-sig")
