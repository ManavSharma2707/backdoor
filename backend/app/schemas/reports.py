"""Reports, decisions, notes and jobs (`api-spec.md` sections 8 and 10)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MoneyStr, QtyIn, QtyStr, UnitPriceStr

DecisionKind = Literal["approved", "edited", "rejected"]
REASON_CODES = (
    "shelf_space",
    "supplier_issue",
    "cash_tight",
    "already_ordered",
    "demand_change",
    "not_needed",
    "other",
)
Section = Literal["buy", "do_not_buy", "watch", "reduce"]
RiskFilter = Literal["critical", "high", "medium", "low", "none"]
ConfidenceFilter = Literal["high", "medium", "low"]
DecisionFilter = Literal["pending", "approved", "edited", "rejected"]
ExportFormat = Literal["pdf", "xlsx", "csv"]
ExportKind = Literal["purchase_list", "plan_lines"]


class ReportListItem(BaseModel):
    id: uuid.UUID
    week_start: date
    version: int
    is_current: bool
    status: str
    generated_at: datetime
    data_cutoff: datetime
    model_version: str
    profile: str | None = None
    backfill: bool = False
    summary: dict[str, Any]


class DecisionOut(BaseModel):
    id: uuid.UUID
    decision: DecisionKind
    final_qty: QtyStr
    final_spend: MoneyStr | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    decided_at: datetime


class DecisionTotals(BaseModel):
    approved: int
    edited: int
    rejected: int
    pending: int
    approved_spend: MoneyStr
    budget: MoneyStr | None
    budget_remaining: MoneyStr | None
    over_budget: bool


class ReportLineOut(BaseModel):
    """One line of the plan as the table shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    base_unit: str
    category_id: uuid.UUID
    category: str
    supplier_id: uuid.UUID | None
    supplier: str | None
    sections: list[str]
    risk_level: str
    confidence: str
    forecast_method: str
    wape: Decimal | None
    demand_7d: QtyStr
    demand_protection: QtyStr
    protection_days: int
    lead_time_days: int
    lead_time_source: str
    on_hand_usable: QtyStr
    expected_expiry_loss: QtyStr
    incoming_confirmed: QtyStr
    incoming_excluded_overdue: QtyStr
    inventory_position: QtyStr
    safety_stock: QtyStr
    raw_qty: QtyStr
    moq_units: QtyStr
    pack_size: QtyStr
    suggested_qty: QtyStr
    allocated_qty: QtyStr
    unfunded_qty: QtyStr
    pack_excess_qty: QtyStr
    unit_cost: UnitPriceStr | None
    est_spend: MoneyStr | None
    funded_spend: MoneyStr | None
    budget_limited: bool
    stockout_probability: Decimal
    projected_stockout_date: date | None
    days_of_cover: Decimal | None
    stock_status: str | None
    excess_qty: QtyStr
    excess_value: MoneyStr
    expiry_exposure_qty: QtyStr
    expiry_exposure_value: MoneyStr
    reason_codes: list[str]
    reason_text: str
    warnings: list[str]
    provenance: dict[str, Any]
    decision: DecisionOut | None = None


class LineDetail(ReportLineOut):
    """A line with everything behind it: provenance, batches, the series and its history."""

    payload: dict[str, Any]
    decisions: list[DecisionOut]
    history: list[dict[str, Any]]
    forecast: list[dict[str, Any]]


class ReportOut(BaseModel):
    id: uuid.UUID
    week_start: date
    version: int
    is_current: bool
    status: str
    generated_at: datetime
    data_cutoff: datetime
    model_version: str
    payload: dict[str, Any]
    summary: dict[str, Any]
    decision_totals: DecisionTotals
    notes_count: int


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionKind
    final_qty: QtyIn | None = Field(
        default=None, description="Needed for an edit. An approval uses the funded quantity."
    )
    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=300)


class DecisionResult(BaseModel):
    line_id: uuid.UUID
    decision: DecisionOut
    totals: DecisionTotals
    off_pack: bool = False


class BulkDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    decision: Literal["approved", "rejected"]
    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=300)


class SkippedLine(BaseModel):
    line_id: uuid.UUID
    reason: str


class BulkDecisionResult(BaseModel):
    applied: int
    skipped: list[SkippedLine]
    totals: DecisionTotals


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1000)
    line_id: uuid.UUID | None = None


class NoteOut(BaseModel):
    id: uuid.UUID
    line_id: uuid.UUID | None
    source: str
    body: str
    author: str | None = None
    created_at: datetime


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date | None = Field(default=None, description="A Monday. Defaults to this week.")
    force: bool = False


class JobRunOut(BaseModel):
    id: uuid.UUID
    job_name: str
    run_key: str
    status: str
    attempts: int
    started_at: datetime
    finished_at: datetime | None
    result: dict[str, Any] | None
    error: str | None


class PoDraftLine(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: QtyStr
    unit_cost: UnitPriceStr
    line_value: MoneyStr


class PoDraftOut(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier: str
    status: str
    expected_date: date | None
    value: MoneyStr
    lines: list[PoDraftLine]


class PoDraftResult(BaseModel):
    purchase_orders: list[PoDraftOut]
    skipped: list[SkippedLine]


class ScenarioIn(BaseModel):
    """Changes for a what if run. Nothing is saved."""

    model_config = ConfigDict(extra="forbid")

    weekly_budget: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    clear_budget: bool = False
    service_level: float | None = Field(default=None, ge=0.5, le=0.999)
    review_period_days: int | None = Field(default=None, ge=1, le=28)
    demand_multiplier: float = Field(default=1.0, ge=0.1, le=5.0)
    lead_time_delta_by_supplier: dict[uuid.UUID, int] = Field(default_factory=dict)
    supplier_delay_days: dict[uuid.UUID, int] = Field(default_factory=dict)
    excluded_product_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    forced_include_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class ScenarioOut(BaseModel):
    base: dict[str, Any]
    scenario: dict[str, Any]
    changes: dict[str, Any]
    lines_changed: list[dict[str, Any]]
    note: str
