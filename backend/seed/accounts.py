"""Owner accounts and business settings for the demo tenants."""

from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.core.security import PasswordPolicyError, PasswordService, validate_password
from seed.model import K_USER, UTC, Catalog, make_uuid, tenant_uuid
from seed.sim import TenantData

CREATED = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
MIN_PASSWORD_LENGTH = 12


class MissingPassword(RuntimeError):
    pass


def owner_password(settings: Settings) -> str:
    password = settings.demo_owner_password.get_secret_value()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise MissingPassword(
            "DEMO_OWNER_PASSWORD is not set or shorter than 12 characters. Set it in .env first."
        )
    return password


def owner_row(catalog: Catalog, password_hash: str) -> tuple[Any, ...]:
    p = catalog.profile
    return (
        make_uuid(p.index, K_USER, 1),
        tenant_uuid(p),
        p.owner_email,
        password_hash,
        p.owner_name,
        "owner",
        True,
        CREATED,
        CREATED,
        CREATED,
    )


def password_policy_problem(catalog: Catalog, password: str) -> str | None:
    """Why the app would refuse this password for a new account, or None. Seeding still works
    with a weak password because the hash is written directly, but a public demo should not."""
    p = catalog.profile
    try:
        validate_password(password, email=p.owner_email, business_name=p.name)
    except PasswordPolicyError as exc:
        return str(exc)
    return None


def hash_password(settings: Settings, password: str) -> str:
    return PasswordService(settings).hash(password)


# Measured on 2026-10-14 against the Prompt 4 engine (light profile, first plan of 2026-10-12):
# the unconstrained need of the plan divided by the cost of goods estimate below. It puts the
# budget at about 70 percent of the need for fmcg_a (scenario S08) and 105 percent for the others
# (S09). Re-measure after a change to the engine's replenishment rules (`D-077`).
ENGINE_NEED_CALIBRATION = {"fmcg_a": 1.158, "fmcg_b": 0.443, "med_a": 0.579, "med_b": 0.7525}


def weekly_budget(data: TenantData, factor: float, scale: float, key: str = "") -> str | None:
    """Budget as a share of the weekly need. The need is estimated from the last 8 weeks of cost of
    goods sold plus 10 percent for the festival run up, then calibrated to what the engine plans."""
    weeks = data.weekly_cogs[-8:]
    if not weeks:
        return None
    need = sum(weeks) / len(weeks) * 1.10 * ENGINE_NEED_CALIBRATION.get(key, 1.0)
    budget = max(5000.0 * scale, round(need * factor / 500.0) * 500.0)
    return f"{budget:.2f}"


def settings_row(catalog: Catalog, budget: str | None) -> tuple[Any, ...]:
    return (tenant_uuid(catalog.profile), budget, CREATED)
