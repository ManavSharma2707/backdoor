"""Reading reports: the list, the headline, the filtered lines and one line with its history."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, any_, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.core.deps import TenantContext
from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.core.pagination import PageParams, paginate, parse_sort
from app.models.catalogue import Category, Product
from app.models.intelligence import (
    RecommendationDecision,
    RecommendationLine,
    ReportNote,
    WeeklyReport,
)
from app.models.suppliers import Supplier
from app.models.tenancy import User
from app.schemas.reports import (
    DecisionOut,
    LineDetail,
    NoteOut,
    ReportLineOut,
    ReportListItem,
    ReportOut,
)
from app.services.common import not_found

PAISA = Decimal("0.01")


def decision_out(d: RecommendationDecision, unit_cost: Decimal | None) -> DecisionOut:
    spend = None if unit_cost is None else (d.final_qty * unit_cost).quantize(PAISA)
    return DecisionOut(
        id=d.id,
        decision=d.decision,
        final_qty=d.final_qty,
        final_spend=spend,  # type: ignore[arg-type]
        reason_code=d.reason_code,
        reason_text=d.reason_text,
        decided_at=d.created_at,
    )


class ReportService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id

    # ------------------------------------------------------------------ reports

    def _report(self, report_id: uuid.UUID) -> WeeklyReport:
        row = self.session.execute(
            select(WeeklyReport).where(
                WeeklyReport.tenant_id == self.tenant_id, WeeklyReport.id == report_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise not_found("plan")
        return row

    def ready_report(self, report_id: uuid.UUID) -> WeeklyReport:
        report = self._report(report_id)
        if report.status != "ready":
            raise AppError(ErrorCode.REPORT_NOT_READY)
        return report

    def list_reports(self, params: PageParams) -> tuple[list[ReportListItem], int]:
        stmt = (
            select(WeeklyReport)
            .where(WeeklyReport.tenant_id == self.tenant_id)
            .order_by(WeeklyReport.week_start.desc(), WeeklyReport.version.desc())
        )
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(WeeklyReport)
                .where(WeeklyReport.tenant_id == self.tenant_id)
            )
            or 0
        )
        rows = (
            self.session.execute(stmt.limit(params.page_size).offset(params.offset)).scalars().all()
        )
        return [self._list_item(r) for r in rows], int(total)

    @staticmethod
    def _list_item(r: WeeklyReport) -> ReportListItem:
        return ReportListItem(
            id=r.id,
            week_start=r.week_start,
            version=r.version,
            is_current=r.is_current,
            status=r.status,
            generated_at=r.generated_at,
            data_cutoff=r.data_cutoff,
            model_version=r.model_version,
            profile=(r.payload or {}).get("profile"),
            backfill=bool((r.payload or {}).get("backfill", False)),
            summary=r.summary,
        )

    def latest(self) -> WeeklyReport:
        row = self.session.execute(
            select(WeeklyReport)
            .where(
                WeeklyReport.tenant_id == self.tenant_id,
                WeeklyReport.is_current,
                WeeklyReport.status == "ready",
            )
            .order_by(WeeklyReport.week_start.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            raise not_found("plan")
        return row

    def header(self, report: WeeklyReport) -> dict[str, Any]:
        """The payload without the per line data, for the report page headline."""
        payload = dict(report.payload)
        payload.pop("lines", None)
        return payload

    def get(self, report_id: uuid.UUID) -> ReportOut:
        from app.services.decision_service import DecisionService

        report = self.ready_report(report_id)
        notes = (
            self.session.scalar(
                select(func.count())
                .select_from(ReportNote)
                .where(ReportNote.tenant_id == self.tenant_id, ReportNote.report_id == report.id)
            )
            or 0
        )
        return ReportOut(
            id=report.id,
            week_start=report.week_start,
            version=report.version,
            is_current=report.is_current,
            status=report.status,
            generated_at=report.generated_at,
            data_cutoff=report.data_cutoff,
            model_version=report.model_version,
            payload=self.header(report),
            summary=report.summary,
            decision_totals=DecisionService(self.session, self.ctx).totals(report),
            notes_count=int(notes),
        )

    # ------------------------------------------------------------------ lines

    def _lines_stmt(self, report: WeeklyReport) -> Select[Any]:
        return (
            select(RecommendationLine, Product, Category, Supplier)
            .join(
                Product,
                and_(
                    Product.tenant_id == RecommendationLine.tenant_id,
                    Product.id == RecommendationLine.product_id,
                ),
            )
            .join(
                Category,
                and_(Category.tenant_id == Product.tenant_id, Category.id == Product.category_id),
            )
            .outerjoin(
                Supplier,
                and_(
                    Supplier.tenant_id == RecommendationLine.tenant_id,
                    Supplier.id == RecommendationLine.supplier_id,
                ),
            )
            .where(
                RecommendationLine.tenant_id == self.tenant_id,
                RecommendationLine.run_id == report.recommendation_run_id,
            )
        )

    def _live_decision_kind(self) -> Any:
        return (
            select(RecommendationDecision.decision)
            .where(
                RecommendationDecision.tenant_id == RecommendationLine.tenant_id,
                RecommendationDecision.line_id == RecommendationLine.id,
                RecommendationDecision.superseded_at.is_(None),
            )
            .scalar_subquery()
        )

    def live_decisions(self, line_ids: list[uuid.UUID]) -> dict[uuid.UUID, RecommendationDecision]:
        if not line_ids:
            return {}
        rows = self.session.execute(
            select(RecommendationDecision).where(
                RecommendationDecision.tenant_id == self.tenant_id,
                RecommendationDecision.line_id.in_(line_ids),
                RecommendationDecision.superseded_at.is_(None),
            )
        ).scalars()
        return {d.line_id: d for d in rows}

    def lines(
        self,
        report_id: uuid.UUID,
        params: PageParams,
        *,
        section: str | None,
        supplier_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
        risk: str | None,
        confidence: str | None,
        decision: str | None,
        q: str | None,
        sort: str | None,
    ) -> tuple[list[ReportLineOut], int]:
        report = self.ready_report(report_id)
        stmt = self._lines_stmt(report)
        if section:
            stmt = stmt.where(literal(section) == any_(RecommendationLine.sections))
        if supplier_id:
            stmt = stmt.where(RecommendationLine.supplier_id == supplier_id)
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if risk:
            stmt = stmt.where(RecommendationLine.risk_level == risk)
        if confidence:
            stmt = stmt.where(RecommendationLine.confidence == confidence)
        if decision:
            kind = self._live_decision_kind()
            stmt = stmt.where(kind.is_(None) if decision == "pending" else kind == decision)
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like))
            )
        order = parse_sort(
            sort,
            {
                "name": func.lower(Product.name),
                "sku": Product.sku,
                "risk": func.array_position(
                    text("ARRAY['critical','high','medium','low','none']"),
                    RecommendationLine.risk_level,
                ),
                "spend": RecommendationLine.est_spend,
                "supplier": func.lower(Supplier.name),
                "suggested": RecommendationLine.suggested_qty,
                "cover": RecommendationLine.days_of_cover,
                "priority": RecommendationLine.priority_score,
            },
            "risk:asc,name:asc",
        )
        rows, total = paginate(self.session, stmt.order_by(*order), params)
        decided = self.live_decisions([r[0].id for r in rows])
        return [self._line_out(r, decided.get(r[0].id)) for r in rows], total

    def _line_out(self, row: Any, live: RecommendationDecision | None) -> ReportLineOut:
        line: RecommendationLine = row[0]
        product: Product = row[1]
        category: Category = row[2]
        supplier: Supplier | None = row[3]
        decision = decision_out(live, line.unit_cost) if live else None
        funded = (
            None
            if line.unit_cost is None
            else (line.allocated_qty * line.unit_cost).quantize(PAISA)
        )
        return ReportLineOut(
            id=line.id,
            product_id=line.product_id,
            sku=product.sku,
            name=product.name,
            base_unit=product.base_unit,
            category_id=category.id,
            category=category.name,
            supplier_id=line.supplier_id,
            supplier=supplier.name if supplier else None,
            sections=line.sections,
            risk_level=line.risk_level,
            confidence=line.confidence,
            forecast_method=line.forecast_method,
            wape=line.wape,
            demand_7d=line.demand_7d,
            demand_protection=line.demand_protection,
            protection_days=line.protection_days,
            lead_time_days=line.lead_time_days,
            lead_time_source=line.lead_time_source,
            on_hand_usable=line.on_hand_usable,
            expected_expiry_loss=line.expected_expiry_loss,
            incoming_confirmed=line.incoming_confirmed,
            incoming_excluded_overdue=line.incoming_excluded_overdue,
            inventory_position=line.inventory_position,
            safety_stock=line.safety_stock,
            raw_qty=line.raw_qty,
            moq_units=line.moq_units,
            pack_size=line.pack_size,
            suggested_qty=line.suggested_qty,
            allocated_qty=line.allocated_qty,
            unfunded_qty=line.unfunded_qty,
            pack_excess_qty=line.pack_excess_qty,
            unit_cost=line.unit_cost,
            est_spend=line.est_spend,
            funded_spend=funded,
            budget_limited=line.budget_limited,
            stockout_probability=line.stockout_probability,
            projected_stockout_date=line.projected_stockout_date,
            days_of_cover=line.days_of_cover,
            stock_status=line.stock_status,
            excess_qty=line.excess_qty,
            excess_value=line.excess_value,
            expiry_exposure_qty=line.expiry_exposure_qty,
            expiry_exposure_value=line.expiry_exposure_value,
            reason_codes=line.reason_codes,
            reason_text=line.reason_text,
            warnings=line.warnings,
            provenance=line.provenance,
            decision=decision,
        )

    def line_detail(self, report_id: uuid.UUID, line_id: uuid.UUID) -> LineDetail:
        report = self.ready_report(report_id)
        stmt = self._lines_stmt(report).where(RecommendationLine.id == line_id)
        row = self.session.execute(stmt).first()
        if row is None:
            raise not_found("plan line")
        line: RecommendationLine = row[0]
        base = self._line_out(row, self.live_decisions([line_id]).get(line_id))
        decisions = (
            self.session.execute(
                select(RecommendationDecision)
                .where(
                    RecommendationDecision.tenant_id == self.tenant_id,
                    RecommendationDecision.line_id == line_id,
                )
                .order_by(RecommendationDecision.created_at.desc())
            )
            .scalars()
            .all()
        )
        payload_line = (report.payload.get("lines") or {}).get(str(line_id), {})
        forecast = payload_line.get("forecast") or {}
        start = date.fromisoformat(forecast.get("start", report.week_start.isoformat()))
        series = [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "forecast": y,
                "lower": forecast.get("lower", [])[i]
                if i < len(forecast.get("lower", []))
                else None,
                "upper": forecast.get("upper", [])[i]
                if i < len(forecast.get("upper", []))
                else None,
            }
            for i, y in enumerate(forecast.get("yhat", []))
        ]
        return LineDetail(
            **base.model_dump(),
            payload={k: v for k, v in payload_line.items() if k != "forecast"},
            decisions=[decision_out(d, line.unit_cost) for d in decisions],
            history=self._history(line.product_id, report.week_start),
            forecast=series,
        )

    def _history(self, product_id: uuid.UUID, week: date) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text(
                """
                SELECT stat_date, units_sold - units_returned, availability_state
                FROM daily_product_stats
                WHERE tenant_id = :t AND product_id = :p AND stat_date >= :s AND stat_date < :e
                ORDER BY stat_date
                """
            ),
            {"t": self.tenant_id, "p": product_id, "s": week - timedelta(days=56), "e": week},
        ).all()
        return [{"date": r[0].isoformat(), "units": str(r[1]), "state": r[2]} for r in rows]

    # ------------------------------------------------------------------ notes

    def notes(self, report_id: uuid.UUID) -> list[NoteOut]:
        self._report(report_id)
        rows = self.session.execute(
            select(ReportNote, User.full_name)
            .outerjoin(User, User.id == ReportNote.author_user_id)
            .where(ReportNote.tenant_id == self.tenant_id, ReportNote.report_id == report_id)
            .order_by(ReportNote.created_at)
        ).all()
        return [
            NoteOut(
                id=n.id,
                line_id=n.line_id,
                source=n.source,
                body=n.body,
                author=name,
                created_at=n.created_at,
            )
            for n, name in rows
        ]
