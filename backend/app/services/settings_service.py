"""Business settings: read with lazy defaults, update with an audited diff."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService, changed_fields
from app.core.db import transaction
from app.core.deps import TenantContext
from app.models.tenancy import BusinessSettings
from app.schemas.settings import SettingsPatch

PATCHABLE = (
    "weekly_budget",
    "service_level",
    "review_period_days",
    "default_lead_time_days",
    "near_expiry_days",
    "nonmoving_days",
    "slow_cover_days",
    "excess_horizon_days",
    "forecast_horizon_days",
    "backtest_origins",
    "stale_count_days",
    "sellable_shelf_life_fraction",
    "censor_policy",
    "pack_rounding",
    "priority_weights",
    "apply_festival_lead_padding",
    "agents_enabled",
)


def snapshot(row: BusinessSettings) -> dict[str, Any]:
    return {name: getattr(row, name) for name in PATCHABLE}


class SettingsService:
    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def get(self) -> BusinessSettings:
        """The tenant's settings. A tenant created without a row gets the defaults."""
        with transaction(self.session):
            return self._row_for_update(lock=False)

    def update(self, patch: SettingsPatch) -> BusinessSettings:
        with transaction(self.session):
            row = self._row_for_update(lock=True)
            before = snapshot(row)
            for name in patch.model_fields_set:
                value = getattr(patch, name)
                if name == "priority_weights" and value is not None:
                    value = value.model_dump()
                setattr(row, name, value)
            self.session.flush()
            self.session.refresh(row)
            old, new = changed_fields(before, snapshot(row))
            if new:
                AuditService(self.session).record(
                    AuditAction.SETTINGS_UPDATE,
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    meta=self.ctx.meta,
                    entity_type="business_settings",
                    entity_id=self.ctx.tenant_id,
                    before=old,
                    after=new,
                )
            return row

    def _row_for_update(self, *, lock: bool) -> BusinessSettings:
        self.session.execute(
            insert(BusinessSettings)
            .values(tenant_id=self.ctx.tenant_id)
            .on_conflict_do_nothing(index_elements=[BusinessSettings.tenant_id])
        )
        stmt = select(BusinessSettings).where(BusinessSettings.tenant_id == self.ctx.tenant_id)
        stmt = stmt.execution_options(populate_existing=True)
        if lock:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one()
