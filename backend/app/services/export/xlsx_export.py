"""Excel export (`report-spec.md` section 5), written with XlsxWriter.

The buy list carries live formulas (spend is quantity times cost, the totals row is a SUBTOTAL so
filters update it) and every formula also stores its computed value, so a viewer that does not
recalculate still shows numbers. A check cell compares the formula total with the engine total.
"""

import io
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import xlsxwriter

from app.services.export.common import (
    DEMO_NOTICE,
    SOURCE_LABEL,
    ExportData,
    ExportLine,
    dec,
    instant,
)

MONEY = "[$₹-4009]#,##0.00"
QTY = "#,##0.###"
PCT = "0%"
DATE = "dd mmm yyyy"
HEADER_FILL = "#F5F3EE"
SHEETS = (
    "Summary",
    "Buy list",
    "By supplier",
    "Watch",
    "Do not buy",
    "Reduce exposure",
    "Expiry batches",
    "Festival",
    "Budget",
    "Data notes",
    "Accuracy",
)


class Book:
    """Formats and small helpers shared by the sheets."""

    def __init__(self, buffer: io.BytesIO) -> None:
        self.wb = xlsxwriter.Workbook(
            buffer,
            {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False},
        )
        self.wb.set_properties({"title": "Monday plan", "author": "Backroom"})
        # Created in the final order, then filled one by one.
        self.sheets = {name: self.wb.add_worksheet(name) for name in SHEETS}
        base = {"font_name": "Calibri", "font_size": 10, "valign": "top"}
        self.text = self.wb.add_format({**base, "text_wrap": True})
        self.plain = self.wb.add_format(base)
        self.bold = self.wb.add_format({**base, "bold": True})
        self.title = self.wb.add_format({**base, "bold": True, "font_size": 14})
        self.header = self.wb.add_format(
            {
                **base,
                "bold": True,
                "bottom": 1,
                "bg_color": HEADER_FILL,
                "text_wrap": True,
                "valign": "vcenter",
            }
        )
        self.money = self.wb.add_format({**base, "num_format": MONEY})
        self.money_bold = self.wb.add_format({**base, "num_format": MONEY, "bold": True, "top": 1})
        self.qty = self.wb.add_format({**base, "num_format": QTY})
        self.pct = self.wb.add_format({**base, "num_format": PCT})
        self.int = self.wb.add_format({**base, "num_format": "0"})
        self.date = self.wb.add_format({**base, "num_format": DATE, "align": "left"})
        self.total_label = self.wb.add_format({**base, "bold": True, "top": 1})
        self.note = self.wb.add_format({**base, "italic": True, "font_color": "#6B665D"})
        self.warn = self.wb.add_format({**base, "bold": True, "font_color": "#8A4B00"})

    def sheet(self, name: str, widths: list[int], headers: list[str]) -> Any:
        ws = self.sheets[name]
        for i, w in enumerate(widths):
            ws.set_column(i, i, w)
        ws.set_row(0, 30)
        for i, h in enumerate(headers):
            ws.write_string(0, i, h, self.header)
        ws.freeze_panes(1, 0)
        return ws


def _num(value: Any) -> float | None:
    return None if value in (None, "") else float(Decimal(str(value)))


def _dt(value: date) -> datetime:
    return datetime.combine(value, time())


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _write_date(ws: Any, row: int, col: int, value: str | None, fmt: Any, blank: Any) -> None:
    d = _date(value)
    if d is None:
        ws.write_blank(row, col, None, blank)
    else:
        ws.write_datetime(row, col, _dt(d), fmt)


def sources(line: ExportLine) -> str:
    prov = line.data.get("provenance", {})
    keep = ("forecast", "lead_time", "safety_stock", "unit_cost", "pack")
    names = {
        "forecast": "Forecast",
        "lead_time": "Delivery time",
        "safety_stock": "Buffer stock",
        "unit_cost": "Cost",
        "pack": "Pack",
    }
    return ", ".join(
        f"{names[k]} {SOURCE_LABEL.get(prov.get(k, ''), '')}".strip() for k in keep if k in prov
    )


# --------------------------------------------------------------------------- sheets


def write_summary(b: Book, data: ExportData, buy_total_cell: str, buy_total: Decimal) -> None:
    ws = b.sheets["Summary"]
    ws.set_column(0, 0, 38)
    ws.set_column(1, 1, 34)
    s = data.summary
    ws.write_string(0, 0, data.tenant_name, b.title)
    rows: list[tuple[str, Any, Any]] = [
        ("Monday plan, week of", data.week, "date"),
        ("Data up to", data.payload["data_cutoff"][:10], "isodate"),
        ("Generated", instant(data.report.generated_at), "text"),
        ("Version", data.report.version, "int"),
        ("Model", data.payload["model_version"], "text"),
        ("Profile", data.payload["profile"], "text"),
    ]
    r = 2
    for label, value, kind in rows:
        ws.write_string(r, 0, label, b.bold)
        if kind == "date":
            ws.write_datetime(r, 1, _dt(value), b.date)
        elif kind == "isodate":
            _write_date(ws, r, 1, value, b.date, b.plain)
        elif kind == "int":
            ws.write_number(r, 1, value, b.int)
        else:
            ws.write_string(r, 1, str(value), b.plain)
        r += 1
    if data.is_synthetic:
        ws.write_string(r, 0, DEMO_NOTICE, b.warn)
        r += 1
    r += 1
    money_rows = [
        ("Planned spend (funded)", s["planned_spend"]),
        ("Needed spend", s["needed_spend"]),
        ("Budget", s["budget"]),
        ("Budget remaining", s["budget_remaining"]),
        ("Shortfall", s["shortfall"]),
        ("Stock not moving, value", s["non_moving_value"]),
        ("Stock that may expire, value", s["expiry_exposure_value"]),
        ("Expired stock, value", s["expired_value"]),
    ]
    for label, value in money_rows:
        ws.write_string(r, 0, label, b.bold)
        if value is None:
            ws.write_string(r, 1, "No limit set", b.plain)
        else:
            ws.write_number(r, 1, float(Decimal(value)), b.money)
        r += 1
    counts = [
        ("Lines to buy", s["lines_buy"]),
        ("Lines not to buy yet", s["lines_do_not_buy"]),
        ("Lines to watch", s["lines_watch"]),
        ("Lines to reduce", s["lines_reduce"]),
        ("Critical lines", s["critical_count"]),
        ("Batches near expiry", s["near_expiry_batches"]),
        ("Data errors", s["dq_errors"]),
        ("Data warnings", s["dq_warnings"]),
        ("Forecast confidence, high", s["confidence_mix"]["high"]),
        ("Forecast confidence, fair", s["confidence_mix"]["medium"]),
        ("Forecast confidence, low", s["confidence_mix"]["low"]),
    ]
    for label, value in counts:
        ws.write_string(r, 0, label, b.bold)
        ws.write_number(r, 1, value, b.int)
        r += 1
    if s.get("festival_note"):
        ws.write_string(r, 0, "Festival", b.bold)
        ws.write_string(r, 1, s["festival_note"], b.plain)
        r += 1
    r += 1
    ws.write_string(r, 0, "Buy list total (from the Buy list sheet)", b.bold)
    ws.write_formula(r, 1, f"='Buy list'!{buy_total_cell}", b.money, float(buy_total))


def write_buy_list(b: Book, data: ExportData) -> tuple[str, Decimal]:
    headers = [
        "Supplier",
        "SKU",
        "Product",
        "Category",
        "Forecast for days to cover",
        "Days to cover",
        "Sellable stock",
        "Incoming",
        "Buffer stock",
        "Shortfall",
        "Pack of",
        "Minimum order",
        "Suggested",
        "Funded quantity",
        "Unit cost",
        "Funded spend",
        "Your decision",
        "Decided quantity",
        "Decided spend",
        "Risk",
        "Forecast confidence",
        "Reason",
        "Sources",
    ]
    widths = [22, 11, 28, 18, 12, 9, 10, 9, 9, 9, 8, 9, 10, 10, 10, 13, 12, 10, 13, 9, 11, 60, 38]
    ws = b.sheet("Buy list", widths, headers)
    lines = data.section_lines("buy")
    funded_total = Decimal(0)
    decided_total = Decimal(0)
    for i, ln in enumerate(lines, start=1):
        d = ln.data
        supplier = (d.get("supplier") or {}).get("name", "No supplier")
        values: list[Any] = [
            supplier,
            d["sku"],
            d["name"],
            d["category"],
            _num(d["demand_protection"]),
            d["protection_days"],
            _num(d["on_hand_usable"]),
            _num(d["incoming_confirmed"]),
            _num(d["safety_stock"]),
            _num(d["raw_qty"]),
            _num(d["pack_size"]),
            _num(d["moq_units"]),
            _num(d["suggested_qty"]),
            _num(d["allocated_qty"]),
        ]
        fmts = [
            b.text,
            b.plain,
            b.text,
            b.text,
            b.qty,
            b.int,
            b.qty,
            b.qty,
            b.qty,
            b.qty,
            b.qty,
            b.qty,
            b.qty,
            b.qty,
        ]
        for c, (v, f) in enumerate(zip(values, fmts, strict=True)):
            if isinstance(v, str):
                ws.write_string(i, c, v, f)
            elif v is None:
                ws.write_blank(i, c, None, f)
            else:
                ws.write_number(i, c, v, f)
        cost = _num(d["unit_cost"])
        row = i + 1  # one based row number for formulas
        if cost is None:
            ws.write_blank(i, 14, None, b.money)
            ws.write_string(i, 15, "No price", b.plain)
        else:
            ws.write_number(i, 14, cost, b.money)
            ws.write_formula(i, 15, f"=N{row}*O{row}", b.money, float(ln.funded_spend))
        funded_total += ln.funded_spend
        ws.write_string(
            i, 16, {"pending": "Pending"}.get(ln.decision, ln.decision.capitalize()), b.plain
        )
        if ln.final_qty is not None and ln.decision != "pending":
            ws.write_number(i, 17, float(ln.final_qty), b.qty)
            if cost is not None:
                ws.write_formula(
                    i,
                    18,
                    f"=R{row}*O{row}",
                    b.money,
                    float(ln.order_spend)
                    if ln.decision != "rejected"
                    else float((ln.final_qty * ln.unit_cost).quantize(Decimal("0.01"))),
                )
                decided_total += ln.order_spend if ln.decision != "rejected" else Decimal(0)
        else:
            ws.write_blank(i, 17, None, b.qty)
            ws.write_blank(i, 18, None, b.money)
        ws.write_string(i, 19, d["risk_label"], b.plain)
        ws.write_string(i, 20, d["confidence_label"], b.plain)
        ws.write_string(i, 21, d["reason_text"], b.text)
        ws.write_string(i, 22, sources(ln), b.text)
    last = len(lines)
    total_row = last + 1
    ws.autofilter(0, 0, max(last, 1), len(headers) - 1)
    ws.write_string(total_row, 0, "Total (follows the filter)", b.total_label)
    first, end = 2, max(last + 1, 2)
    ws.write_formula(
        total_row, 15, f"=SUBTOTAL(109,P{first}:P{end})", b.money_bold, float(funded_total)
    )
    ws.write_formula(
        total_row, 18, f"=SUBTOTAL(109,S{first}:S{end})", b.money_bold, float(decided_total)
    )
    engine_total = data.buy_total()
    ws.write_string(total_row + 2, 0, "Total from the engine", b.bold)
    ws.write_number(total_row + 2, 15, float(engine_total), b.money)
    ws.write_string(total_row + 3, 0, "Check", b.bold)
    ok = "Matches the plan" if funded_total == engine_total else "Check the totals"
    ws.write_formula(
        total_row + 3,
        15,
        f"=IF(ROUND(SUBTOTAL(109,P{first}:P{end})-P{total_row + 3},2)=0,"
        '"Matches the plan","Check the totals")',
        b.bold,
        ok,
    )
    return f"P{total_row + 1}", funded_total


def write_by_supplier(b: Book, data: ExportData) -> None:
    ws = b.sheets["By supplier"]
    for i, w in enumerate([12, 34, 9, 9, 11, 11, 14, 14]):
        ws.set_column(i, i, w)
    headers = [
        "SKU",
        "Product",
        "Pack of",
        "Packs",
        "Quantity",
        "Unit cost",
        "Line total",
        "Delivery by",
    ]
    ws.write_string(0, 0, "Purchase list by supplier, ready to send", b.title)
    r = 2
    groups: dict[str, list[ExportLine]] = {}
    for ln in data.purchase_lines():
        groups.setdefault(ln.data["supplier"]["name"], []).append(ln)
    for name in sorted(groups, key=str.lower):
        ws.write_string(r, 0, name, b.bold)
        r += 1
        for c, h in enumerate(headers):
            ws.write_string(r, c, h, b.header)
        r += 1
        first = r + 1
        total = Decimal(0)
        for ln in sorted(groups[name], key=lambda x: x.data["name"].lower()):
            d = ln.data
            qty = (
                ln.final_qty
                if ln.final_qty is not None and ln.decision != "pending"
                else ln.funded_qty
            )
            pack = dec(d["pack_size"]) or Decimal(1)
            ws.write_string(r, 0, d["sku"], b.plain)
            ws.write_string(r, 1, d["name"], b.text)
            ws.write_number(r, 2, float(pack), b.qty)
            ws.write_number(r, 3, float(qty / pack), b.qty)
            ws.write_number(r, 4, float(qty), b.qty)
            cost = ln.unit_cost or Decimal(0)
            ws.write_number(r, 5, float(cost), b.money)
            line_total = (qty * cost).quantize(Decimal("0.01"))
            ws.write_formula(r, 6, f"=E{r + 1}*F{r + 1}", b.money, float(line_total))
            total += line_total
            _write_date(ws, r, 7, d["arrival_date"], b.date, b.plain)
            r += 1
        ws.write_string(r, 5, "Subtotal", b.total_label)
        ws.write_formula(r, 6, f"=SUM(G{first}:G{r})", b.money_bold, float(total))
        r += 2
    if not groups:
        ws.write_string(2, 0, "Nothing to order yet.", b.note)


def _table(
    b: Book,
    name: str,
    headers: list[str],
    widths: list[int],
    rows: list[list[Any]],
    formats: list[Any],
) -> Any:
    ws = b.sheet(name, widths, headers)
    for i, row in enumerate(rows, start=1):
        for c, (v, f) in enumerate(zip(row, formats, strict=True)):
            if v is None or v == "":
                ws.write_blank(i, c, None, f)
            elif isinstance(v, date):
                ws.write_datetime(
                    i,
                    c,
                    __import__("datetime").datetime.combine(v, __import__("datetime").time()),
                    b.date,
                )
            elif isinstance(v, bool):
                ws.write_string(i, c, "Yes" if v else "No", b.plain)
            elif isinstance(v, int | float | Decimal):
                ws.write_number(i, c, float(v), f)
            else:
                ws.write_string(i, c, str(v), f)
    ws.autofilter(0, 0, max(len(rows), 1), len(headers) - 1)
    return ws


def write_watch(b: Book, data: ExportData) -> None:
    rows = []
    for ln in data.section_lines("watch"):
        d = ln.data
        rows.append(
            [
                d["sku"],
                d["name"],
                (d.get("supplier") or {}).get("name", ""),
                d["risk_label"],
                d["stockout_probability"],
                _date(d["projected_stockout_date"]),
                _num(d["on_hand_usable"]),
                _num(d["incoming_confirmed"]),
                _num(d["incoming_excluded_overdue"]),
                d["reason_text"],
            ]
        )
    _table(
        b,
        "Watch",
        [
            "SKU",
            "Product",
            "Supplier",
            "Risk",
            "Chance of running out",
            "Likely to run out on",
            "Sellable stock",
            "Incoming",
            "Incoming ignored (late)",
            "What to do",
        ],
        [11, 30, 22, 9, 12, 14, 10, 10, 12, 70],
        rows,
        [b.plain, b.text, b.text, b.plain, b.pct, b.date, b.qty, b.qty, b.qty, b.text],
    )


def write_do_not_buy(b: Book, data: ExportData) -> None:
    rows = []
    for ln in data.section_lines("do_not_buy"):
        d = ln.data
        rows.append(
            [
                d["sku"],
                d["name"],
                d["days_of_cover"],
                _num(d["on_hand_usable"]),
                _num(d["incoming_confirmed"]),
                d["reason_text"],
            ]
        )
    _table(
        b,
        "Do not buy",
        ["SKU", "Product", "Days of cover", "Sellable stock", "Incoming", "Reason"],
        [11, 32, 10, 12, 10, 80],
        rows,
        [b.plain, b.text, b.qty, b.qty, b.qty, b.text],
    )


def write_reduce(b: Book, data: ExportData) -> None:
    labels = {
        "slow": "Selling slowly",
        "non_moving": "Not selling",
        "unverified": "Check first",
        "normal": "",
        "new": "",
    }
    rows = []
    for ln in data.section_lines("reduce"):
        d = ln.data
        rows.append(
            [
                d["sku"],
                d["name"],
                labels.get(d["stock_status"], ""),
                _num(d["on_hand_usable"]),
                d["days_of_cover"],
                _num(d["excess_qty"]),
                _num(d["excess_value"]),
                _num(d["expiry_exposure_qty"]),
                _num(d["expiry_exposure_value"]),
                _num(d["expired_value"]),
                d["reason_text"],
            ]
        )
    _table(
        b,
        "Reduce exposure",
        [
            "SKU",
            "Product",
            "Stock status",
            "Sellable stock",
            "Days of cover",
            "Extra stock",
            "Extra stock value",
            "May expire",
            "May expire value",
            "Expired value",
            "Why",
        ],
        [11, 30, 14, 12, 10, 10, 14, 10, 14, 13, 70],
        rows,
        [b.plain, b.text, b.plain, b.qty, b.qty, b.qty, b.money, b.qty, b.money, b.money, b.text],
    )


def write_expiry(b: Book, data: ExportData) -> None:
    options = {
        "sell_first": "Sell first",
        "return_to_supplier": "Return to supplier",
        "write_off": "Write off",
    }
    rows = []
    for e in data.payload["expiry_batches"]:
        rows.append(
            [
                e["product"],
                e["sku"],
                e["batch_no"] or "No batch",
                _date(e["expiry_date"]),
                e["days_to_expiry"],
                _num(e["qty"]),
                _num(e["exposure_qty"]),
                _num(e["exposure_value"]),
                "Expired, write off" if e["status"] == "expired" else "Near expiry",
                ", ".join(options[o] for o in e["options"]),
            ]
        )
    _table(
        b,
        "Expiry batches",
        [
            "Product",
            "SKU",
            "Batch",
            "Expiry date",
            "Days to expiry",
            "Quantity",
            "May expire",
            "Value at cost",
            "Status",
            "Options",
        ],
        [30, 11, 12, 13, 10, 10, 10, 14, 18, 40],
        rows,
        [b.text, b.plain, b.plain, b.date, b.int, b.qty, b.qty, b.money, b.plain, b.text],
    )


def write_festival(b: Book, data: ExportData) -> None:
    rows = []
    for f in data.payload["festival"]:
        if not f["categories"]:
            rows.append(
                [
                    f["name"],
                    _date(f["start"]),
                    _date(f["end"]),
                    f["days_away"],
                    "",
                    None,
                    "",
                    None,
                    None,
                    "",
                    f["delivery_padding_days"],
                ]
            )
        for c in f["categories"]:
            rows.append(
                [
                    f["name"],
                    _date(f["start"]),
                    _date(f["end"]),
                    f["days_away"],
                    c["category"],
                    c["multiplier"],
                    c["label_text"],
                    _num(c["forecast_with_effect"]),
                    _num(c["forecast_without_effect"]),
                    c["evidence"],
                    f["delivery_padding_days"],
                ]
            )
    _table(
        b,
        "Festival",
        [
            "Festival",
            "Starts",
            "Ends",
            "Days away",
            "Category",
            "Effect (times)",
            "Basis",
            "Forecast with effect",
            "Forecast without effect",
            "Evidence",
            "Delivery delay (days)",
        ],
        [22, 13, 13, 9, 24, 10, 36, 12, 12, 60, 12],
        rows,
        [b.text, b.date, b.date, b.int, b.text, b.qty, b.text, b.qty, b.qty, b.text, b.int],
    )


def write_budget(b: Book, data: ExportData) -> None:
    ws = b.sheets["Budget"]
    for i, w in enumerate([34, 14, 14, 14, 14, 12, 12]):
        ws.set_column(i, i, w)
    v = data.payload["budget"]
    ws.write_string(0, 0, "Budget view", b.title)
    rows = [
        ("Budget", v["budget"]),
        ("Needed", v["needed"]),
        ("Funded", v["funded"]),
        ("Shortfall", v["shortfall"]),
        ("Unfunded value", v["unfunded_value"]),
    ]
    for i, (label, value) in enumerate(rows, start=2):
        ws.write_string(i, 0, label, b.bold)
        if value is None:
            ws.write_string(i, 1, "No limit set", b.plain)
        else:
            ws.write_number(i, 1, float(Decimal(value)), b.money)
    ws.write_string(8, 0, v["claim"], b.warn if v["constrained"] else b.plain)
    ws.merge_range(9, 0, 9, 6, v["explanation"], b.text)
    ws.set_row(9, 44)
    r = 11
    for title, key in (
        ("Lines the budget could not fund", "unfunded_lines"),
        ("Lines still at risk", "still_at_risk"),
    ):
        ws.write_string(r, 0, title, b.bold)
        r += 1
        for c, h in enumerate(
            ["Product", "SKU", "Suggested", "Funded", "Unfunded", "Unfunded value", "Risk"]
        ):
            ws.write_string(r, c, h, b.header)
        r += 1
        for ln in v[key]:
            ws.write_string(r, 0, ln["name"], b.text)
            ws.write_string(r, 1, ln["sku"], b.plain)
            ws.write_number(r, 2, float(ln["suggested_qty"]), b.qty)
            ws.write_number(r, 3, float(ln["allocated_qty"]), b.qty)
            ws.write_number(r, 4, float(ln["unfunded_qty"]), b.qty)
            if ln["unfunded_value"] is None:
                ws.write_blank(r, 5, None, b.money)
            else:
                ws.write_number(r, 5, float(ln["unfunded_value"]), b.money)
            ws.write_string(r, 6, ln["risk_level"].capitalize(), b.plain)
            r += 1
        r += 1


def write_notes(b: Book, data: ExportData) -> None:
    severity = {"error": "Error", "warning": "Warning", "info": "Note"}
    rows = [
        [severity[n["severity"]], n["code"], n["message"], n["count"], n.get("fix_hint") or ""]
        for n in data.payload["data_notes"]
    ]
    _table(
        b,
        "Data notes",
        ["Severity", "Code", "What we found", "Count", "What to do"],
        [10, 28, 80, 8, 50],
        rows,
        [b.plain, b.plain, b.text, b.int, b.text],
    )


def write_accuracy(b: Book, data: ExportData) -> None:
    s = data.payload["backtest_summary"]
    ws = b.sheets["Accuracy"]
    for i, w in enumerate([34, 18, 22, 10, 10, 12, 12, 14]):
        ws.set_column(i, i, w)
    ws.write_string(0, 0, "Forecast accuracy on past weeks", b.title)
    items = [
        ("Forecast error (steady sellers)", s["tenant_wape"]),
        ("Forecast tendency", s["bias"]),
        ("Same method with no learning, error", s["baseline_wape"]),
        ("Same weekday last week, error", s["seasonal_naive_wape"]),
    ]
    for i, (label, value) in enumerate(items, start=2):
        ws.write_string(i, 0, label, b.bold)
        if value is None:
            ws.write_string(i, 1, "Not measured", b.plain)
        else:
            ws.write_number(i, 1, value, b.pct)
    ws.write_string(
        7,
        0,
        f"Measured over {s['n_origins']} past Mondays. Demo data is simulated."
        if data.is_synthetic
        else f"Measured over {s['n_origins']} past Mondays.",
        b.note,
    )
    r = 9
    for c, h in enumerate(
        [
            "Segment",
            "Demand type",
            "Method",
            "Products",
            "Points",
            "Average miss",
            "Error",
            "Baseline miss",
        ]
    ):
        ws.write_string(r, c, h, b.header)
    for seg in s["by_segment"]:
        r += 1
        ws.write_string(r, 0, seg["segment"].split("|")[0], b.text)
        ws.write_string(r, 1, seg["demand_class"], b.plain)
        ws.write_string(r, 2, seg["method"], b.plain)
        ws.write_number(r, 3, seg["products"], b.int)
        ws.write_number(r, 4, seg["points"], b.int)
        ws.write_number(r, 5, seg["mae"], b.qty)
        if seg["wape"] is None:
            ws.write_string(r, 6, "Not meaningful", b.plain)
        else:
            ws.write_number(r, 6, seg["wape"], b.pct)
        if seg["baseline_mae"] is None:
            ws.write_blank(r, 7, None, b.qty)
        else:
            ws.write_number(r, 7, seg["baseline_mae"], b.qty)


def build_xlsx(data: ExportData) -> bytes:
    buffer = io.BytesIO()
    book = Book(buffer)
    buy_cell, total = write_buy_list(book, data)
    write_summary(book, data, buy_cell, total)
    write_by_supplier(book, data)
    write_watch(book, data)
    write_do_not_buy(book, data)
    write_reduce(book, data)
    write_expiry(book, data)
    write_festival(book, data)
    write_budget(book, data)
    write_notes(book, data)
    write_accuracy(book, data)
    book.sheets["Summary"].activate()
    book.wb.close()
    return buffer.getvalue()
