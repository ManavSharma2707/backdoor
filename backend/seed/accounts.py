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


def weekly_budget(data: TenantData, factor: float, scale: float) -> str | None:
    """Budget as a share of the weekly need. Need is estimated from the last 8 weeks of cost of
    goods sold plus 10 percent for the festival run up. The engine in Prompt 4 re-checks the share."""
    weeks = data.weekly_cogs[-8:]
    if not weeks:
        return None
    need = sum(weeks) / len(weeks) * 1.10
    budget = max(5000.0 * scale, round(need * factor / 500.0) * 500.0)
    return f"{budget:.2f}"


def settings_row(catalog: Catalog, budget: str | None) -> tuple[Any, ...]:
    return (tenant_uuid(catalog.profile), budget, CREATED)
