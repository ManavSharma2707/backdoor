"""Builds an export file from a stored report and records that it was made."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService
from app.core.db import transaction
from app.core.deps import TenantContext
from app.services.export.common import ExportData, file_name, load_export

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    filename: str
    media_type: str


def render(data: ExportData, fmt: str, kind: str) -> ExportFile:
    """The file itself. Heavy libraries load here, not when the API starts."""
    if fmt == "pdf":
        from app.services.export.pdf_export import build_pdf

        return ExportFile(build_pdf(data), file_name(data, "pdf"), MEDIA_TYPES["pdf"])
    if fmt == "xlsx":
        from app.services.export.xlsx_export import build_xlsx

        return ExportFile(build_xlsx(data), file_name(data, "xlsx"), MEDIA_TYPES["xlsx"])
    from app.services.export.csv_export import build_csv

    return ExportFile(build_csv(data, kind), file_name(data, "csv", kind), MEDIA_TYPES["csv"])


def export_report(
    session: Session,
    ctx: TenantContext,
    report_id: uuid.UUID,
    *,
    fmt: str,
    kind: str = "purchase_list",
    section: str | None = None,
    supplier_id: uuid.UUID | None = None,
) -> ExportFile:
    data = load_export(session, ctx, report_id, section=section, supplier_id=supplier_id)
    result = render(data, fmt, kind)
    with transaction(session):
        AuditService(session).record(
            AuditAction.REPORT_EXPORT,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            meta=ctx.meta,
            entity_type="weekly_report",
            entity_id=report_id,
            after={"format": fmt, "kind": kind, "section": section, "bytes": len(result.content)},
        )
    return result
