"""Decisions on plan lines, notes, and draft purchase orders made from approved lines.

Decisions are append only. A new decision for a line ends the live one (`superseded_at`) and adds
a row, so the history of what the owner did stays. Totals are recomputed from the live decisions
each time and never stored, so they cannot drift from the lines.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService
from app.core.clock import now_utc
from app.core.db import transaction
from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.models.catalogue import Product
from app.models.intelligence import (
    RecommendationDecision,
    RecommendationLine,
    ReportNote,
    WeeklyReport,
)
from app.models.purchasing import PurchaseOrder, PurchaseOrderLine
from app.models.suppliers import Supplier
from app.schemas.common import ErrorDetail
from app.schemas.purchasing import POCreate, POLineIn
from app.schemas.reports import (
    REASON_CODES,
    BulkDecisionIn,
    BulkDecisionResult,
    DecisionIn,
    DecisionResult,
    DecisionTotals,
    NoteIn,
    NoteOut,
    PoDraftLine,
    PoDraftOut,
    PoDraftResult,
    SkippedLine,
)
from app.services.common import conflict, invalid, not_found
from app.services.purchasing_service import PurchasingService
from app.services.report_service import PAISA, ReportService, decision_out

ZERO = Decimal(0)
ACTIONS = {
    "approved": AuditAction.DECISION_APPROVE,
    "edited": AuditAction.DECISION_EDIT,
    "rejected": AuditAction.DECISION_REJECT,
}


class DecisionService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.audit = AuditService(session)
        self.reports = ReportService(session, ctx)

    # ------------------------------------------------------------------ lookups

    def _line(self, line_id: uuid.UUID, *, for_update: bool = False) -> RecommendationLine:
        stmt = select(RecommendationLine).where(
            RecommendationLine.tenant_id == self.tenant_id, RecommendationLine.id == line_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        line = self.session.execute(stmt).scalar_one_or_none()
        if line is None:
            raise not_found("plan line")
        return line

    def _report_of(self, line: RecommendationLine) -> WeeklyReport:
        report = self.session.execute(
            select(WeeklyReport).where(
                WeeklyReport.tenant_id == self.tenant_id,
                WeeklyReport.recommendation_run_id == line.run_id,
            )
        ).scalar_one_or_none()
        if report is None:
            raise not_found("plan")
        return report

    # ------------------------------------------------------------------ totals

    def totals(self, report: WeeklyReport) -> DecisionTotals:
        """Counts and spend of the live decisions, against the budget of the plan."""
        lines = self.session.execute(
            select(
                RecommendationLine.id,
                RecommendationLine.unit_cost,
                RecommendationLine.allocated_qty,
                RecommendationLine.sections,
            ).where(
                RecommendationLine.tenant_id == self.tenant_id,
                RecommendationLine.run_id == report.recommendation_run_id,
            )
        ).all()
        live = {
            d.line_id: d
            for d in self.session.execute(
                select(RecommendationDecision)
                .join(
                    RecommendationLine,
                    (RecommendationLine.tenant_id == RecommendationDecision.tenant_id)
                    & (RecommendationLine.id == RecommendationDecision.line_id),
                )
                .where(
                    RecommendationDecision.tenant_id == self.tenant_id,
                    RecommendationDecision.superseded_at.is_(None),
                    RecommendationLine.run_id == report.recommendation_run_id,
                )
            ).scalars()
        }
        counts = {"approved": 0, "edited": 0, "rejected": 0}
        spend = ZERO
        pending = 0
        for line_id, cost, allocated, sections in lines:
            decision = live.get(line_id)
            if decision is None:
                if "buy" in sections and allocated > 0:
                    pending += 1
                continue
            counts[decision.decision] += 1
            if decision.decision != "rejected" and cost is not None:
                spend += decision.final_qty * cost
        budget_text = (report.summary or {}).get("budget")
        budget = Decimal(budget_text) if budget_text else None
        spend = spend.quantize(PAISA)
        return DecisionTotals(
            approved=counts["approved"],
            edited=counts["edited"],
            rejected=counts["rejected"],
            pending=pending,
            approved_spend=spend,
            budget=budget,
            budget_remaining=None if budget is None else budget - spend,
            over_budget=budget is not None and spend > budget,
        )

    # ------------------------------------------------------------------ deciding

    def _validate(
        self, line: RecommendationLine, body: DecisionIn
    ) -> tuple[Decimal, bool, str | None, str | None]:
        """The quantity to store, whether it is off the pack size, and the cleaned reason."""
        code = body.reason_code
        if code is not None and code not in REASON_CODES:
            raise invalid("reason_code", f"must be one of {', '.join(REASON_CODES)}")
        text = body.reason_text.strip() if body.reason_text else None
        if code == "other" and not text:
            raise invalid("reason_text", "is needed when the reason is other")
        if body.decision == "rejected":
            return ZERO, False, code, text
        if body.decision == "approved":
            if line.allocated_qty <= 0:
                raise conflict(
                    "Nothing is funded for this line. Edit the quantity to order it.",
                    field="decision",
                )
            return line.allocated_qty, False, code, text
        if body.final_qty is None or body.final_qty <= 0:
            raise invalid("final_qty", "must be more than zero for an edit")
        pack = line.pack_size if line.pack_size > 0 else Decimal(1)
        off_pack = (body.final_qty % pack) != 0
        if off_pack and code != "other":
            raise invalid("final_qty", f"must be a multiple of the pack size, {pack.normalize():f}")
        return body.final_qty, off_pack, code, text

    def _apply(
        self, line: RecommendationLine, kind: str, qty: Decimal, code: str | None, text: str | None
    ) -> RecommendationDecision:
        now = now_utc()
        before = self.session.execute(
            select(RecommendationDecision).where(
                RecommendationDecision.tenant_id == self.tenant_id,
                RecommendationDecision.line_id == line.id,
                RecommendationDecision.superseded_at.is_(None),
            )
        ).scalar_one_or_none()
        if before is not None:
            before.superseded_at = now
            self.session.flush()
        row = RecommendationDecision(
            tenant_id=self.tenant_id,
            line_id=line.id,
            decided_by=self.ctx.user_id,
            decision=kind,
            final_qty=qty,
            reason_code=code,
            reason_text=text,
            created_at=now,
        )
        self.session.add(row)
        self.session.flush()
        self.audit.record(
            ACTIONS[kind],
            tenant_id=self.tenant_id,
            user_id=self.ctx.user_id,
            meta=self.ctx.meta,
            entity_type="recommendation_line",
            entity_id=line.id,
            before=None
            if before is None
            else {"decision": before.decision, "final_qty": before.final_qty},
            after={"decision": kind, "final_qty": qty, "reason_code": code},
        )
        return row

    def decide(self, line_id: uuid.UUID, body: DecisionIn) -> DecisionResult:
        with transaction(self.session):
            line = self._line(line_id, for_update=True)
            report = self._report_of(line)
            self._require_current(report)
            qty, off_pack, code, text = self._validate(line, body)
            row = self._apply(line, body.decision, qty, code, text)
            return DecisionResult(
                line_id=line.id,
                decision=decision_out(row, line.unit_cost),
                totals=self.totals(report),
                off_pack=off_pack,
            )

    @staticmethod
    def _require_current(report: WeeklyReport) -> None:
        if not report.is_current:
            raise conflict("This plan has been replaced by a newer version.")

    def bulk(self, report_id: uuid.UUID, body: BulkDecisionIn) -> BulkDecisionResult:
        with transaction(self.session):
            report = self.reports.ready_report(report_id)
            self._require_current(report)
            lines = {
                ln.id: ln
                for ln in self.session.execute(
                    select(RecommendationLine)
                    .where(
                        RecommendationLine.tenant_id == self.tenant_id,
                        RecommendationLine.run_id == report.recommendation_run_id,
                        RecommendationLine.id.in_(body.line_ids),
                    )
                    .with_for_update()
                ).scalars()
            }
            unknown = [str(i) for i in body.line_ids if i not in lines]
            if unknown:
                raise not_found("plan line", field="line_ids")
            applied = 0
            skipped: list[SkippedLine] = []
            single = DecisionIn(
                decision=body.decision, reason_code=body.reason_code, reason_text=body.reason_text
            )
            for line_id in dict.fromkeys(body.line_ids):
                line = lines[line_id]
                try:
                    qty, _, code, text = self._validate(line, single)
                except AppError as exc:
                    skipped.append(SkippedLine(line_id=line_id, reason=exc.message))
                    continue
                self._apply(line, body.decision, qty, code, text)
                applied += 1
            return BulkDecisionResult(applied=applied, skipped=skipped, totals=self.totals(report))

    # ------------------------------------------------------------------ notes

    def add_note(self, report_id: uuid.UUID, body: NoteIn) -> NoteOut:
        with transaction(self.session):
            report = self.reports._report(report_id)
            if body.line_id is not None:
                line = self._line(body.line_id)
                if line.run_id != report.recommendation_run_id:
                    raise not_found("plan line", field="line_id")
            note = ReportNote(
                tenant_id=self.tenant_id,
                report_id=report.id,
                line_id=body.line_id,
                author_user_id=self.ctx.user_id,
                source="user",
                body=body.body.strip(),
            )
            self.session.add(note)
            self.session.flush()
            self.audit.record(
                AuditAction.REPORT_NOTE,
                tenant_id=self.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="weekly_report",
                entity_id=report.id,
                after={"line_id": body.line_id, "length": len(note.body)},
            )
            return NoteOut(
                id=note.id,
                line_id=note.line_id,
                source=note.source,
                body=note.body,
                author=None,
                created_at=note.created_at,
            )

    # ------------------------------------------------------------------ purchase orders

    def create_purchase_orders(self, report_id: uuid.UUID) -> PoDraftResult:
        """One draft order per supplier from the approved and edited lines.

        A line without a supplier or a price blocks the whole request with a 409 that lists the
        lines, so the owner fixes them first. Lines already turned into an order are skipped.
        """
        with transaction(self.session):
            report = self.reports.ready_report(report_id)
            self._require_current(report)
            rows = self.session.execute(
                select(RecommendationLine, RecommendationDecision, Product)
                .join(
                    RecommendationDecision,
                    (RecommendationDecision.tenant_id == RecommendationLine.tenant_id)
                    & (RecommendationDecision.line_id == RecommendationLine.id)
                    & RecommendationDecision.superseded_at.is_(None),
                )
                .join(
                    Product,
                    (Product.tenant_id == RecommendationLine.tenant_id)
                    & (Product.id == RecommendationLine.product_id),
                )
                .where(
                    RecommendationLine.tenant_id == self.tenant_id,
                    RecommendationLine.run_id == report.recommendation_run_id,
                    RecommendationDecision.decision.in_(("approved", "edited")),
                    RecommendationDecision.final_qty > 0,
                )
                .order_by(Product.name)
            ).all()
            ordered = set(
                self.session.execute(
                    select(PurchaseOrderLine.recommendation_line_id).where(
                        PurchaseOrderLine.tenant_id == self.tenant_id,
                        PurchaseOrderLine.recommendation_line_id.in_([r[0].id for r in rows]),
                    )
                ).scalars()
            )
            blocked = [
                ErrorDetail(field=f"lines[{p.sku}]", issue="needs a supplier and a price")
                for ln, _d, p in rows
                if ln.id not in ordered and (ln.supplier_id is None or ln.unit_cost is None)
            ]
            if blocked:
                raise AppError(ErrorCode.MISSING_SUPPLIER_OR_COST, details=blocked)
            skipped = [
                SkippedLine(line_id=ln.id, reason="Already on a purchase order.")
                for ln, _d, _p in rows
                if ln.id in ordered
            ]
            groups: dict[
                uuid.UUID, list[tuple[RecommendationLine, RecommendationDecision, Product]]
            ] = {}
            for ln, d, p in rows:
                if ln.id not in ordered and ln.supplier_id is not None:
                    groups.setdefault(ln.supplier_id, []).append((ln, d, p))
            service = PurchasingService(self.session, self.ctx)
            created: list[PoDraftOut] = []
            for supplier_id, items in groups.items():
                po = service.create(
                    POCreate(
                        supplier_id=supplier_id,
                        notes=f"From the plan of {report.week_start.isoformat()}",
                        lines=[
                            POLineIn(
                                product_id=p.id,
                                quantity_ordered=d.final_qty,
                                unit_cost=ln.unit_cost,
                            )
                            for ln, d, p in items
                        ],
                    )
                )
                self.session.execute(
                    update(PurchaseOrder)
                    .where(PurchaseOrder.tenant_id == self.tenant_id, PurchaseOrder.id == po.id)
                    .values(
                        source="recommendation", recommendation_run_id=report.recommendation_run_id
                    )
                )
                by_product = {p.id: ln.id for ln, _d, p in items}
                for po_line in self.session.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.tenant_id == self.tenant_id,
                        PurchaseOrderLine.po_id == po.id,
                    )
                ).scalars():
                    po_line.recommendation_line_id = by_product.get(po_line.product_id)
                supplier = self.session.get(Supplier, supplier_id)
                created.append(
                    self._po_out(po, supplier.name if supplier else po.supplier_name, items)
                )
            self.session.flush()
            self.audit.record(
                AuditAction.REPORT_PO_CREATE,
                tenant_id=self.tenant_id,
                user_id=self.ctx.user_id,
                meta=self.ctx.meta,
                entity_type="weekly_report",
                entity_id=report.id,
                after={"orders": len(created), "skipped": len(skipped)},
            )
            return PoDraftResult(purchase_orders=created, skipped=skipped)

    @staticmethod
    def _po_out(po: Any, supplier: str, items: list[tuple[Any, Any, Any]]) -> PoDraftOut:
        lines = [
            PoDraftLine(
                product_id=p.id,
                sku=p.sku,
                name=p.name,
                quantity=d.final_qty,
                unit_cost=ln.unit_cost,
                line_value=(d.final_qty * ln.unit_cost).quantize(PAISA),
            )
            for ln, d, p in items
        ]
        return PoDraftOut(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            supplier=supplier,
            status=po.status,
            expected_date=po.expected_date,
            value=po.subtotal_estimated,
            lines=lines,
        )


def count_lines(session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(RecommendationLine)
            .where(RecommendationLine.tenant_id == tenant_id, RecommendationLine.run_id == run_id)
        )
        or 0
    )
