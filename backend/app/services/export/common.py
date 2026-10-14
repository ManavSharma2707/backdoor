"""What every export format needs: the stored report, the live decisions and the totals.

Exports are built from the saved snapshot, never recomputed, so a file always matches the screen
and the other formats. Money is summed as `Decimal` rows of whole paise, which is why the totals
of the PDF, the Excel file and the CSV agree to the paisa.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import IST
from app.core.deps import TenantContext
from app.models.intelligence import RecommendationDecision, RecommendationLine, WeeklyReport
from app.models.tenancy import Tenant
from app.services.report_service import ReportService

PAISA = Decimal("0.01")
DEMO_NOTICE = "Demo data. Numbers are simulated."
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
SOURCE_LABEL = {"observed": "Observed", "calculated": "Calculated", "assumed": "Assumed"}


def dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def inr(value: Decimal | str | float | int | None, places: int = 0) -> str:
    """Rupees with Indian digit grouping: 182340 becomes 1,82,340."""
    if value is None:
        return ""
    amount = Decimal(str(value)).quantize(Decimal(1) if places == 0 else Decimal(10) ** -places)
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(amount):f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return f"₹{sign}{whole}" + (f".{frac}" if places else "")


def num(value: Decimal | str | None, places: int = 3) -> str:
    """A quantity without trailing zeros: 12.500 becomes 12.5, 20.000 becomes 20."""
    if value is None:
        return ""
    text = f"{Decimal(str(value)):.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def day(value: date | str | None) -> str:
    if not value:
        return ""
    d = value if isinstance(value, date) else date.fromisoformat(str(value))
    return f"{d.day} {d.strftime('%b %Y')}"


def instant(value: datetime) -> str:
    local = value.astimezone(IST)
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{local.minute:02d} {suffix}"


def text_safe(value: str | None) -> str:
    """Stop a spreadsheet from reading a text cell as a formula."""
    if not value:
        return ""
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


@dataclass
class ExportLine:
    """One plan line with its live decision, as the exports show it."""

    data: dict[str, Any]
    decision: str  # approved, edited, rejected or pending
    final_qty: Decimal | None
    reason: str | None

    @property
    def sku(self) -> str:
        return str(self.data["sku"])

    @property
    def unit_cost(self) -> Decimal | None:
        return dec(self.data["unit_cost"])

    @property
    def funded_qty(self) -> Decimal:
        return dec(self.data["allocated_qty"]) or Decimal(0)

    @property
    def funded_spend(self) -> Decimal:
        cost = self.unit_cost
        return Decimal(0) if cost is None else (self.funded_qty * cost).quantize(PAISA)

    @property
    def order_qty(self) -> Decimal:
        """The quantity to order: the decided one when there is a decision, else the funded one."""
        if self.final_qty is not None and self.decision in ("approved", "edited"):
            return self.final_qty
        return self.funded_qty

    @property
    def order_spend(self) -> Decimal:
        cost = self.unit_cost
        return Decimal(0) if cost is None else (self.order_qty * cost).quantize(PAISA)


@dataclass
class ExportData:
    report: WeeklyReport
    payload: dict[str, Any]
    tenant_slug: str
    tenant_name: str
    is_synthetic: bool
    lines: list[ExportLine]
    by_id: dict[str, ExportLine]
    any_decisions: bool
    section: str | None = None
    supplier_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def week(self) -> date:
        return self.report.week_start

    @property
    def summary(self) -> dict[str, Any]:
        return dict(self.payload["summary"])

    def section_lines(self, section: str) -> list[ExportLine]:
        ids = self.payload["sections"].get(section, [])
        return [self.by_id[i] for i in ids if i in self.by_id and self._wanted(self.by_id[i])]

    def _wanted(self, line: ExportLine) -> bool:
        supplier = (line.data.get("supplier") or {}).get("id")
        return self.supplier_id is None or supplier == self.supplier_id

    def buy_total(self) -> Decimal:
        return sum((ln.funded_spend for ln in self.section_lines("buy")), Decimal(0))

    def purchase_lines(self) -> list[ExportLine]:
        """Lines that go on the purchase list. With decisions: approved and edited only. Without:
        every funded line. A line without a supplier or a price cannot be ordered."""
        out = []
        for ln in self.section_lines("buy"):
            if ln.data.get("supplier") is None or ln.unit_cost is None:
                continue
            if self.any_decisions:
                if ln.decision in ("approved", "edited") and (ln.final_qty or 0) > 0:
                    out.append(ln)
            elif ln.funded_qty > 0:
                out.append(ln)
        return out


def file_name(data: ExportData, extension: str, kind: str | None = None) -> str:
    stem = "monday-plan-lines" if kind == "plan_lines" else "monday-plan"
    return f"backroom_{data.tenant_slug}_{stem}_{data.week.isoformat()}.{extension}"


def load_export(
    session: Session,
    ctx: TenantContext,
    report_id: uuid.UUID,
    *,
    section: str | None = None,
    supplier_id: uuid.UUID | None = None,
) -> ExportData:
    report = ReportService(session, ctx).ready_report(report_id)
    tenant = session.get(Tenant, ctx.tenant_id)
    decisions = {
        str(d.line_id): d
        for d in session.execute(
            select(RecommendationDecision)
            .join(
                RecommendationLine,
                (RecommendationLine.tenant_id == RecommendationDecision.tenant_id)
                & (RecommendationLine.id == RecommendationDecision.line_id),
            )
            .where(
                RecommendationDecision.tenant_id == ctx.tenant_id,
                RecommendationDecision.superseded_at.is_(None),
                RecommendationLine.run_id == report.recommendation_run_id,
            )
        ).scalars()
    }
    lines = []
    for line_id, data in report.payload["lines"].items():
        d = decisions.get(line_id)
        lines.append(
            ExportLine(
                data=data,
                decision=d.decision if d else "pending",
                final_qty=d.final_qty if d else None,
                reason=(d.reason_text or d.reason_code) if d else None,
            )
        )
    return ExportData(
        report=report,
        payload=report.payload,
        tenant_slug=tenant.slug if tenant else "business",
        tenant_name=report.payload["tenant"]["name"],
        is_synthetic=bool(report.payload["tenant"]["is_synthetic"]),
        lines=lines,
        by_id={ln.data["id"]: ln for ln in lines},
        any_decisions=bool(decisions),
        section=section,
        supplier_id=str(supplier_id) if supplier_id else None,
    )
