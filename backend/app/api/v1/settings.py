"""Business settings endpoints (`api-spec.md` section 3)."""

from fastapi import APIRouter, Depends

from app.core.deps import OwnerCtx, SessionDep, owner_context
from app.schemas.settings import SettingsOut, SettingsPatch
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(owner_context)])


@router.get("", response_model=SettingsOut, summary="Business settings")
def get_settings_endpoint(ctx: OwnerCtx, session: SessionDep) -> SettingsOut:
    return SettingsOut.model_validate(SettingsService(session, ctx).get())


@router.patch("", response_model=SettingsOut, summary="Change business settings")
def patch_settings(body: SettingsPatch, ctx: OwnerCtx, session: SessionDep) -> SettingsOut:
    """Only the fields sent change. Changes apply from the next plan, never retroactively."""
    return SettingsOut.model_validate(SettingsService(session, ctx).update(body))
