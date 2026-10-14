"""PDF export (`report-spec.md` section 4), written with ReportLab.

A4 portrait, 16 mm margins, IBM Plex Sans registered from `app/assets/fonts` so the Rupee sign
prints. Risk is always written as a word, the colour only adds to it.
"""

import io
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.clock import IST
from app.services.export.common import (
    DEMO_NOTICE,
    ExportData,
    ExportLine,
    day,
    dec,
    inr,
    instant,
    num,
)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
MARGIN = 16 * mm
WIDTH = A4[0] - 2 * MARGIN

INK = colors.HexColor("#1E1D1A")
INK_2 = colors.HexColor("#55524A")
INK_3 = colors.HexColor("#6F6A5F")
PRIMARY = colors.HexColor("#1F5A45")
HEADER_FILL = colors.HexColor("#F5F3EE")
RULE = colors.HexColor("#E2DED4")
ACCENT_SOFT = colors.HexColor("#F6EBD3")
RISK_COLOUR = {
    "critical": "#A32A22",
    "high": "#B4530B",
    "medium": "#8A6A0B",
    "low": "#2D6A4F",
    "none": "#55524A",
}
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    for name, file in (
        ("PlexSans", "IBMPlexSans-Regular.ttf"),
        ("PlexSans-Medium", "IBMPlexSans-Medium.ttf"),
        ("PlexSans-SemiBold", "IBMPlexSans-SemiBold.ttf"),
        ("PlexMono", "IBMPlexMono-Regular.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily(
        "PlexSans",
        normal="PlexSans",
        bold="PlexSans-SemiBold",
        italic="PlexSans",
        boldItalic="PlexSans-SemiBold",
    )
    _registered = True


def styles() -> dict[str, ParagraphStyle]:
    base = {"fontName": "PlexSans", "textColor": INK, "fontSize": 8, "leading": 10}
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle(
            "small", **{**base, "fontSize": 6.8, "leading": 8.2, "textColor": INK_2}
        ),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 7, "leading": 8.4}),
        "cell_right": ParagraphStyle(
            "cell_right", **{**base, "fontSize": 7, "leading": 8.4, "alignment": TA_RIGHT}
        ),
        "head": ParagraphStyle(
            "head",
            **{
                **base,
                "fontName": "PlexSans-Medium",
                "fontSize": 6.8,
                "leading": 8,
                "textColor": INK_2,
            },
        ),
        "head_right": ParagraphStyle(
            "head_right",
            **{
                **base,
                "fontName": "PlexSans-Medium",
                "fontSize": 6.8,
                "leading": 8,
                "textColor": INK_2,
                "alignment": TA_RIGHT,
            },
        ),
        "h1": ParagraphStyle(
            "h1", **{**base, "fontName": "PlexSans-SemiBold", "fontSize": 16, "leading": 20}
        ),
        "h2": ParagraphStyle(
            "h2",
            **{
                **base,
                "fontName": "PlexSans-SemiBold",
                "fontSize": 10.5,
                "leading": 13,
                "spaceBefore": 10,
                "spaceAfter": 4,
            },
        ),
        "h3": ParagraphStyle(
            "h3",
            **{
                **base,
                "fontName": "PlexSans-SemiBold",
                "fontSize": 8.5,
                "leading": 11,
                "spaceBefore": 6,
                "spaceAfter": 2,
            },
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label", **{**base, "fontSize": 6.8, "leading": 8, "textColor": INK_3}
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value", **{**base, "fontName": "PlexSans-SemiBold", "fontSize": 14, "leading": 17}
        ),
    }


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def first_sentences(text: str, count: int = 2, limit: int = 190) -> str:
    parts = re.split(r"(?<=[.])\s+", text.strip())
    out = " ".join(parts[:count])
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "."


def heading(st: dict[str, ParagraphStyle], text: str) -> list[Any]:
    """A section heading that never sits alone at the bottom of a page."""
    return [CondPageBreak(38 * mm), Paragraph(esc(text), st["h2"])]


def risk_cell(label: str, level: str, st: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f'<font color="{RISK_COLOUR[level]}">{esc(label)}</font>', st["cell"])


def table(
    rows: list[list[Any]],
    widths: list[float],
    *,
    right_from: int = 1,
    extra: list[Any] | None = None,
) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    t.setStyle(TableStyle(style + (extra or [])))
    return t


class NumberedCanvas(canvas_mod.Canvas):
    """Two passes, so every page can say "Page n of m"."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        meta = self.meta
        self.saveState()
        self.setFont("PlexSans-SemiBold", 8)
        self.setFillColor(INK)
        top = A4[1] - 10 * mm
        self.drawString(MARGIN, top, meta["business"])
        self.setFont("PlexSans", 8)
        self.drawCentredString(A4[0] / 2, top, meta["title"])
        self.drawRightString(A4[0] - MARGIN, top, f"Page {self._pageNumber} of {total}")
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(MARGIN, top - 2.5 * mm, A4[0] - MARGIN, top - 2.5 * mm)
        if meta["demo"]:
            self.setFillColor(ACCENT_SOFT)
            self.rect(MARGIN, top - 8.2 * mm, WIDTH, 4.4 * mm, stroke=0, fill=1)
            self.setFillColor(INK_2)
            self.setFont("PlexSans", 6.8)
            self.drawString(MARGIN + 2 * mm, top - 7 * mm, DEMO_NOTICE)
        self.setFont("PlexSans", 6.8)
        self.setFillColor(INK_3)
        self.drawString(MARGIN, 9 * mm, meta["footer"])
        if meta["demo"]:
            self.drawRightString(A4[0] - MARGIN, 9 * mm, DEMO_NOTICE)
        self.restoreState()


# --------------------------------------------------------------------------- blocks


def kpi_table(data: ExportData, st: dict[str, ParagraphStyle]) -> Table:
    s = data.summary
    budget = s["budget"]
    cells = [
        ("Planned spend", inr(s["planned_spend"])),
        ("Budget", inr(budget) if budget is not None else "No limit set"),
        (
            "Shortfall" if Decimal(s["shortfall"]) > 0 else "Budget remaining",
            inr(s["shortfall"])
            if Decimal(s["shortfall"]) > 0
            else (inr(s["budget_remaining"]) if s["budget_remaining"] is not None else "None"),
        ),
        ("Critical lines", str(s["critical_count"])),
        ("Stock not moving", inr(s["non_moving_value"])),
        ("May expire", inr(s["expiry_exposure_value"])),
    ]
    rows = [
        [Paragraph(esc(label), st["kpi_label"]) for label, _ in cells[:3]],
        [Paragraph(esc(value), st["kpi_value"]) for _, value in cells[:3]],
        [Paragraph(esc(label), st["kpi_label"]) for label, _ in cells[3:]],
        [Paragraph(esc(value), st["kpi_value"]) for _, value in cells[3:]],
    ]
    t = Table(rows, colWidths=[WIDTH / 3] * 3)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                ("LINEBELOW", (0, 1), (-1, 1), 0.25, RULE),
            ]
        )
    )
    return t


def budget_bar(data: ExportData) -> Drawing:
    v = data.payload["budget"]
    height = 16
    d = Drawing(WIDTH, height + 14)
    funded = float(Decimal(v["funded"]))
    needed = float(Decimal(v["needed"]))
    budget = float(Decimal(v["budget"])) if v["budget"] is not None else None
    scale_max = max(needed, budget or 0.0, funded, 1.0)
    bar_w = WIDTH
    d.add(Rect(0, 12, bar_w, height - 4, strokeColor=RULE, fillColor=HEADER_FILL, strokeWidth=0.5))
    d.add(Rect(0, 12, bar_w * funded / scale_max, height - 4, strokeColor=None, fillColor=PRIMARY))
    if needed > funded:
        d.add(
            Rect(
                bar_w * funded / scale_max,
                12,
                bar_w * (needed - funded) / scale_max,
                height - 4,
                strokeColor=None,
                fillColor=colors.HexColor("#E9C9C5"),
            )
        )
    if budget is not None:
        x = bar_w * budget / scale_max
        d.add(Rect(x - 0.5, 8, 1, height, strokeColor=None, fillColor=INK))
    label = f"Funded {inr(v['funded'])} of {inr(v['needed'])} needed"
    if budget is not None:
        label += f". Budget {inr(v['budget'])}."
    d.add(String(0, 1, label, fontName="PlexSans", fontSize=7, fillColor=INK_2))
    return d


def buy_rows(lines: list[ExportLine], st: dict[str, ParagraphStyle]) -> list[list[Any]]:
    head = [
        "Product",
        "Forecast",
        "Stock",
        "Incoming",
        "Buffer",
        "Pack of",
        "Suggested",
        "Funded",
        "Spend",
        "Risk",
        "Reason",
    ]
    rows: list[list[Any]] = [
        [Paragraph(h, st["head_right" if i in range(1, 9) else "head"]) for i, h in enumerate(head)]
    ]
    for ln in lines:
        d = ln.data
        note = f"{d['sku']}, forecast {d['confidence_label'].lower()}"
        if ln.decision != "pending":
            note += f", {ln.decision}"
        if d["blocked"]:
            note += ", no price"
        rows.append(
            [
                Paragraph(
                    f"{esc(d['name'])}<br/><font size='6' color='#6F6A5F'>{esc(note)}</font>",
                    st["cell"],
                ),
                Paragraph(num(d["demand_protection"], 1), st["cell_right"]),
                Paragraph(num(d["on_hand_usable"], 1), st["cell_right"]),
                Paragraph(num(d["incoming_confirmed"], 1), st["cell_right"]),
                Paragraph(num(d["safety_stock"], 1), st["cell_right"]),
                Paragraph(num(d["pack_size"], 1), st["cell_right"]),
                Paragraph(num(d["suggested_qty"], 1), st["cell_right"]),
                Paragraph(num(d["allocated_qty"], 1), st["cell_right"]),
                Paragraph(inr(ln.funded_spend) if d["unit_cost"] else "None", st["cell_right"]),
                risk_cell(d["risk_label"], d["risk_level"], st),
                Paragraph(esc(first_sentences(d["reason_text"], 3, 250)), st["small"]),
            ]
        )
    return rows


BUY_WIDTHS = [
    33 * mm,
    12 * mm,
    10 * mm,
    11 * mm,
    9 * mm,
    9 * mm,
    12 * mm,
    11 * mm,
    16 * mm,
    12 * mm,
]
BUY_WIDTHS.append(WIDTH - sum(BUY_WIDTHS))


def build_story(data: ExportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    s = data.summary
    p = data.payload
    marks: dict[str, int] = {}
    story: list[Any] = [
        Paragraph("Monday plan", st["h1"]),
        Paragraph(f"Week of {day(data.week)}. Data up to {day(_data_through(data))}.", st["body"]),
        Spacer(1, 8),
        kpi_table(data, st),
        Spacer(1, 6),
        budget_bar(data),
    ]
    if s.get("festival_note"):
        story += [Spacer(1, 4), Paragraph(esc(s["festival_note"]), st["body"])]
    mix = s["confidence_mix"]
    story.append(
        Paragraph(
            f"Forecast confidence: {mix['high']} high, {mix['medium']} fair, {mix['low']} low. "
            f"Data notes: {s['dq_errors']} errors, {s['dq_warnings']} warnings.",
            st["small"],
        )
    )

    critical = [ln for ln in data.section_lines("watch") if ln.data["risk_level"] == "critical"][:5]
    story.extend(heading(st, "Most urgent"))
    if critical:
        rows = [
            [
                Paragraph(h, st["head"])
                for h in ("Product", "Supplier", "Stock", "Suggested", "Risk", "Why")
            ]
        ]
        for ln in critical:
            d = ln.data
            rows.append(
                [
                    Paragraph(esc(d["name"]), st["cell"]),
                    Paragraph(
                        esc((d.get("supplier") or {}).get("name", "No supplier")), st["cell"]
                    ),
                    Paragraph(num(d["on_hand_usable"], 1), st["cell_right"]),
                    Paragraph(num(d["suggested_qty"], 1), st["cell_right"]),
                    risk_cell(d["risk_label"], d["risk_level"], st),
                    Paragraph(esc(first_sentences(d["reason_text"], 2, 140)), st["small"]),
                ]
            )
        w = [38 * mm, 30 * mm, 12 * mm, 14 * mm, 14 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))
    else:
        story.append(Paragraph("No line is critical this week.", st["body"]))

    # 2 Buy this week
    marks["buy"] = len(story)
    story.extend(heading(st, "Buy this week"))
    buy = data.section_lines("buy")
    if not buy:
        story.append(Paragraph("Nothing to buy this week.", st["body"]))
    groups: dict[str, list[ExportLine]] = {}
    for ln in buy:
        groups.setdefault((ln.data.get("supplier") or {}).get("name", "No supplier"), []).append(ln)
    for name in sorted(groups, key=str.lower):
        lines = groups[name]
        subtotal = sum((ln.funded_spend for ln in lines), Decimal(0))
        story += [
            CondPageBreak(45 * mm),
            Paragraph(f"{esc(name)}, {len(lines)} lines, {inr(subtotal)}", st["h3"]),
            table(buy_rows(lines, st), BUY_WIDTHS),
        ]
    story.append(Paragraph(f"Total funded: {inr(data.buy_total())}", st["h3"]))

    # 3 Do not buy yet
    marks["do_not_buy"] = len(story)
    story.extend(heading(st, "Do not buy yet"))
    rows = [
        [
            Paragraph(h, st["head_right" if i else "head"])
            for i, h in enumerate(("Product", "Days of cover", "Stock", "Incoming", "Next review"))
        ]
    ]
    for ln in data.section_lines("do_not_buy"):
        d = ln.data
        cover = (
            "No sales expected"
            if d["days_of_cover"] is None
            else ("More than a year" if d["days_of_cover"] > 365 else f"{d['days_of_cover']:.0f}")
        )
        rows.append(
            [
                Paragraph(esc(d["name"]), st["cell"]),
                Paragraph(cover, st["cell_right"]),
                Paragraph(num(d["on_hand_usable"], 1), st["cell_right"]),
                Paragraph(num(d["incoming_confirmed"], 1), st["cell_right"]),
                Paragraph(day(data.week + timedelta(days=7)), st["cell_right"]),
            ]
        )
    if len(rows) > 1:
        w = [72 * mm, 28 * mm, 20 * mm, 20 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))
    else:
        story.append(Paragraph("Every product that is short is on the buy list.", st["body"]))

    # 4 Watch closely
    marks["watch"] = len(story)
    story.extend(heading(st, "Watch closely"))
    rows = [
        [
            Paragraph(h, st["head"])
            for h in ("Product", "Risk", "Chance", "Runs out", "Stock", "What to do")
        ]
    ]
    for ln in data.section_lines("watch"):
        d = ln.data
        rows.append(
            [
                Paragraph(esc(d["name"]), st["cell"]),
                risk_cell(d["risk_label"], d["risk_level"], st),
                Paragraph(f"{round(d['stockout_probability'] * 100)} percent", st["cell_right"]),
                Paragraph(day(d["projected_stockout_date"]) or "Not soon", st["cell_right"]),
                Paragraph(num(d["on_hand_usable"], 1), st["cell_right"]),
                Paragraph(esc(first_sentences(d["reason_text"], 3, 230)), st["small"]),
            ]
        )
    if len(rows) > 1:
        w = [36 * mm, 13 * mm, 15 * mm, 17 * mm, 11 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))
    else:
        story.append(Paragraph("Nothing needs a close watch.", st["body"]))

    # 5 Reduce exposure
    marks["reduce"] = len(story)
    story.extend(heading(st, "Reduce exposure"))
    labels = {"slow": "Selling slowly", "non_moving": "Not selling", "unverified": "Check first"}
    rows = [
        [
            Paragraph(h, st["head_right" if i > 1 else "head"])
            for i, h in enumerate(("Product", "Status", "Stock", "Extra stock", "May expire"))
        ]
    ]
    for ln in data.section_lines("reduce"):
        d = ln.data
        rows.append(
            [
                Paragraph(esc(d["name"]), st["cell"]),
                Paragraph(labels.get(d["stock_status"], "Extra stock"), st["cell"]),
                Paragraph(num(d["on_hand_usable"], 1), st["cell_right"]),
                Paragraph(inr(d["excess_value"]), st["cell_right"]),
                Paragraph(
                    inr(dec(d["expiry_exposure_value"]) + dec(d["expired_value"])), st["cell_right"]
                ),
            ]
        )
    if len(rows) > 1:
        w = [66 * mm, 28 * mm, 20 * mm, 28 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))
    batches = p["expiry_batches"]
    if batches:
        story.append(Paragraph("Batches to act on", st["h3"]))
        names = {
            "sell_first": "Sell first",
            "return_to_supplier": "Return to supplier",
            "write_off": "Write off",
        }
        rows = [
            [
                Paragraph(h, st["head_right" if i in (3, 4) else "head"])
                for i, h in enumerate(
                    ("Product", "Batch", "Expiry", "Quantity", "Value", "Options")
                )
            ]
        ]
        for e in batches[:40]:
            rows.append(
                [
                    Paragraph(esc(e["product"]), st["cell"]),
                    Paragraph(esc(e["batch_no"] or "No batch"), st["cell"]),
                    Paragraph(
                        day(e["expiry_date"]) + (", expired" if e["status"] == "expired" else ""),
                        st["cell"],
                    ),
                    Paragraph(num(e["qty"], 1), st["cell_right"]),
                    Paragraph(inr(e["exposure_value"]), st["cell_right"]),
                    Paragraph(esc(", ".join(names[o] for o in e["options"])), st["small"]),
                ]
            )
        w = [50 * mm, 17 * mm, 26 * mm, 16 * mm, 20 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))

    # 6 Festival and season
    marks["festival"] = len(story)
    story.extend(heading(st, "Festival and season"))
    if not p["festival"]:
        story.append(Paragraph("No festival is due in the next 5 weeks.", st["body"]))
    for f in p["festival"]:
        when = "is on now" if f["days_away"] < 0 else f"starts in {f['days_away']} days"
        story.append(
            Paragraph(f"{esc(f['name'])} {when}, {day(f['start'])} to {day(f['end'])}.", st["h3"])
        )
        if f["delivery_padding_days"]:
            story.append(
                Paragraph(
                    f"Deliveries are expected {f['delivery_padding_days']} days later.", st["small"]
                )
            )
        if f["categories"]:
            rows = [
                [
                    Paragraph(h, st["head_right" if i in (1, 3, 4) else "head"])
                    for i, h in enumerate(("Category", "Effect", "Basis", "With effect", "Without"))
                ]
            ]
            for c in f["categories"]:
                rows.append(
                    [
                        Paragraph(esc(c["category"]), st["cell"]),
                        Paragraph(f"{c['multiplier']:.2f} times", st["cell_right"]),
                        Paragraph(esc(c["label_text"]), st["small"]),
                        Paragraph(num(c["forecast_with_effect"], 0), st["cell_right"]),
                        Paragraph(num(c["forecast_without_effect"], 0), st["cell_right"]),
                    ]
                )
            w = [48 * mm, 20 * mm, 60 * mm, 22 * mm]
            story.append(table(rows, [*w, WIDTH - sum(w)]))
            story.append(
                Paragraph(
                    "Not enough evidence means the forecast is not changed for that category.",
                    st["small"],
                )
            )

    # 7 Budget view
    marks["budget"] = len(story)
    b = p["budget"]
    story.extend(heading(st, "Budget view"))
    story.append(
        Paragraph(
            f"Budget {inr(b['budget']) if b['budget'] is not None else 'not set'}. Needed {inr(b['needed'])}. "
            f"Funded {inr(b['funded'])}. Shortfall {inr(b['shortfall'])}. {esc(b['claim'])}",
            st["body"],
        )
    )
    story.append(Paragraph(esc(b["explanation"]), st["small"]))
    if b["unfunded_lines"]:
        rows = [
            [
                Paragraph(h, st["head_right" if i > 0 else "head"])
                for i, h in enumerate(("Not fully funded", "Suggested", "Funded", "Unfunded value"))
            ]
        ]
        for ln in b["unfunded_lines"][:25]:
            rows.append(
                [
                    Paragraph(esc(ln["name"]), st["cell"]),
                    Paragraph(num(ln["suggested_qty"], 1), st["cell_right"]),
                    Paragraph(num(ln["allocated_qty"], 1), st["cell_right"]),
                    Paragraph(
                        inr(ln["unfunded_value"]) if ln["unfunded_value"] else "", st["cell_right"]
                    ),
                ]
            )
        w = [90 * mm, 25 * mm, 25 * mm]
        story.append(table(rows, [*w, WIDTH - sum(w)]))
    if b["still_at_risk"]:
        story.append(Paragraph("Still at risk after funding", st["h3"]))
        story.append(
            Paragraph(
                esc(
                    ", ".join(
                        f"{ln['name']} ({ln['risk_level']})" for ln in b["still_at_risk"][:20]
                    )
                ),
                st["small"],
            )
        )

    # 8 Data and confidence notes
    marks["notes"] = len(story)
    story.extend(heading(st, "Data and confidence notes"))
    rows = [[Paragraph(h, st["head"]) for h in ("Level", "What we found", "What to do")]]
    labels = {"error": "Error", "warning": "Warning", "info": "Note"}
    for n in p["data_notes"]:
        rows.append(
            [
                Paragraph(labels[n["severity"]], st["cell"]),
                Paragraph(esc(n["message"]), st["small"]),
                Paragraph(esc(n.get("fix_hint") or ""), st["small"]),
            ]
        )
    if len(rows) > 1:
        story.append(table(rows, [16 * mm, 100 * mm, WIDTH - 116 * mm]))
    else:
        story.append(Paragraph("No data problems were found.", st["body"]))

    # How to read this plan
    marks["howto"] = len(story)
    story += [
        CondPageBreak(60 * mm),
        Paragraph("How to read this plan", st["h2"]),
        Paragraph(
            "Each line says how much of a product to order. The suggestion covers the days until the next delivery "
            "and the week after it, plus a buffer for sales running higher than expected. It is rounded up to the "
            "supplier's pack and minimum order.",
            st["body"],
        ),
        Spacer(1, 3),
        Paragraph(
            "Stock you can count on means sellable stock plus confirmed deliveries. Orders that are late are not "
            "counted. Stock that is near expiry or expired is not counted as sellable.",
            st["body"],
        ),
        Spacer(1, 3),
        Paragraph(
            "Forecast confidence is high, fair or low. It drops when delivery times are assumed, when a product was "
            "often out of stock, or when an order is late. Check low confidence lines before you order.",
            st["body"],
        ),
        Paragraph("Assumptions in use", st["h3"]),
    ]
    settings = p["settings"]
    assumptions = [
        f"Service level {round(settings['service_level'] * 100)} percent, review period {settings['review_period_days']} days.",
        f"Default delivery time {settings['default_lead_time_days']} days when a supplier has none.",
        f"Pack rounding: {'always up' if settings['pack_rounding'] == 'up' else 'nearest, only when safe'}.",
        f"Stock near expiry means within {settings['near_expiry_days']} days. Not selling means no sales in {settings['nonmoving_days']} days.",
        "Festival effects are applied only when past sales show a clear and consistent change.",
    ]
    story += [Paragraph(esc(a), st["body"]) for a in assumptions]
    if data.section:
        names = ["buy", "do_not_buy", "watch", "reduce", "festival", "budget", "notes", "howto"]
        start = marks[data.section]
        later = [marks[n] for n in names if marks[n] > start]
        return story[: marks["buy"]] + story[start : min(later)] + story[marks["howto"] :]
    return story


def _data_through(data: ExportData) -> Any:
    cutoff = data.report.data_cutoff.astimezone(IST).date()
    return cutoff - timedelta(days=1)


def build_pdf(data: ExportData) -> bytes:
    register_fonts()
    st = styles()
    buffer = io.BytesIO()
    meta = {
        "business": data.tenant_name,
        "title": f"Monday plan, week of {day(data.week)}",
        "demo": data.is_synthetic,
        "footer": f"Data up to {day(_data_through(data))}. Generated {instant(data.report.generated_at)}.",
    }

    class Canvas(NumberedCanvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.meta = meta

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm,
        bottomMargin=MARGIN,
        title=f"Monday plan {data.week.isoformat()}",
        author="Backroom",
    )
    frame = Frame(
        MARGIN,
        MARGIN,
        WIDTH,
        A4[1] - 2 * MARGIN - 6 * mm,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="plan", frames=[frame])])
    doc.build(build_story(data, st), canvasmaker=Canvas)
    return buffer.getvalue()
