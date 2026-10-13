"""Request dependencies: settings, request metadata, the signed in user and the tenant context.

Tenant identity comes from the access token only. `get_current_user` validates the token and
then checks the database, so a deactivated user or tenant is locked out at once instead of when
the 15 minute token runs out. Routers attach `require_role("owner")` so a missing check is a
test failure, not a silent gap.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import RequestMeta, meta_from_request
from app.core.clock import now_utc
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.logging import bind_request_context
from app.core.messages import ErrorCode
from app.core.ratelimit import keyed_limits
from app.core.security import PasswordService, TokenError, decode_access_token
from app.models.tenancy import Tenant, User

ROLE_RANK = {"staff": 1, "manager": 2, "owner": 3}
WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth", bearerFormat="JWT")


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_password_service(request: Request) -> PasswordService:
    service: PasswordService = request.app.state.password_service
    return service


def get_request_meta(request: Request) -> RequestMeta:
    return meta_from_request(request)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
MetaDep = Annotated[RequestMeta, Depends(get_request_meta)]
SessionDep = Annotated[Session, Depends(get_session)]
PasswordsDep = Annotated[PasswordService, Depends(get_password_service)]


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class TenantContext:
    """Who is acting, for which tenant. Built from the token, never from request input."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    meta: RequestMeta


def unauthenticated() -> AppError:
    return AppError(ErrorCode.UNAUTHENTICATED, headers=WWW_AUTHENTICATE)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: SessionDep,
    settings: SettingsDep,
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated()
    try:
        claims = decode_access_token(settings, credentials.credentials, now=now_utc())
    except TokenError as exc:
        raise unauthenticated() from exc

    row = session.execute(
        select(User.id, User.tenant_id, User.role, User.is_active, Tenant.is_active)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == claims.user_id)
    ).first()
    if row is None:
        raise unauthenticated()
    user_id, tenant_id, role, user_active, tenant_active = row
    if tenant_id != claims.tenant_id or not user_active or not tenant_active:
        raise unauthenticated()

    keyed_limits.check("user", settings.rate_limit_user, str(user_id))
    bind_request_context(tenant_id=str(tenant_id), user_id=str(user_id))
    return CurrentUser(user_id=user_id, tenant_id=tenant_id, role=role)


def get_tenant_context(
    user: Annotated[CurrentUser, Depends(get_current_user)], meta: MetaDep
) -> TenantContext:
    return TenantContext(tenant_id=user.tenant_id, user_id=user.user_id, role=user.role, meta=meta)


def require_role(minimum: str) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory: the caller must have at least `minimum` role."""
    if minimum not in ROLE_RANK:
        raise ValueError(f"Unknown role {minimum!r}")

    def dependency(ctx: Annotated[TenantContext, Depends(get_tenant_context)]) -> TenantContext:
        if ROLE_RANK.get(ctx.role, 0) < ROLE_RANK[minimum]:
            raise AppError(ErrorCode.FORBIDDEN)
        return ctx

    dependency.__name__ = f"require_{minimum}"
    return dependency


# One shared callable, so FastAPI evaluates it once per request however many times it is named.
owner_context = require_role("owner")
OwnerCtx = Annotated[TenantContext, Depends(owner_context)]
