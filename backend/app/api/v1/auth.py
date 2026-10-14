"""Authentication endpoints (`api-spec.md` section 2)."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import Settings
from app.core.deps import (
    MetaDep,
    OwnerCtx,
    PasswordsDep,
    SessionDep,
    SettingsDep,
    unauthenticated,
)
from app.core.errors import AppError, error_response
from app.core.messages import REQUEST_NOT_ALLOWED, SIGNED_OUT, ErrorCode
from app.core.ratelimit import (
    demo_ip_limit,
    limiter,
    login_ip_limit,
    refresh_ip_limit,
    register_ip_limit,
)
from app.models.tenancy import BusinessSettings, Tenant, User
from app.schemas.auth import (
    ChangePasswordRequest,
    DemoLoginRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MessageResponse,
    RegisterRequest,
    SettingsSummary,
    TenantOut,
    UserOut,
)
from app.schemas.common import ErrorEnvelope
from app.services.auth_service import AuthService, IssuedSession

REFRESH_COOKIE = "backroom_rt"
COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "backroom"

router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _service(
    session: SessionDep, settings: SettingsDep, passwords: PasswordsDep, meta: MetaDep
) -> AuthService:
    return AuthService(session, settings, passwords, meta)


ServiceDep = Annotated[AuthService, Depends(_service)]


def require_cookie_csrf(request: Request, settings: SettingsDep) -> None:
    """Defence for the two cookie authenticated endpoints (`security.md`, CSRF).

    The custom header cannot be added by a plain cross site form, and the Origin header, when
    the browser sends one, must be one of ours.
    """
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AppError(ErrorCode.FORBIDDEN, REQUEST_NOT_ALLOWED)
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origins:
        raise AppError(ErrorCode.FORBIDDEN, REQUEST_NOT_ALLOWED)


CsrfDep = Depends(require_cookie_csrf)


def set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def _login_response(issued: IssuedSession) -> LoginResponse:
    return LoginResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
        tenant=TenantOut.model_validate(issued.tenant),
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Sign in",
    responses={401: {"model": ErrorEnvelope, "description": "Email or password is not right"}},
)
@limiter.limit(login_ip_limit)
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    service: ServiceDep,
    settings: SettingsDep,
) -> LoginResponse:
    """Returns a 15 minute access token and sets the refresh cookie."""
    issued = service.login(body.email, body.password)
    set_refresh_cookie(response, settings, issued.refresh_token)
    return _login_response(issued)


@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Rotate the refresh token",
    dependencies=[CsrfDep],
    responses={
        401: {"model": ErrorEnvelope, "description": "Not signed in"},
        403: {"model": ErrorEnvelope, "description": "Request refused"},
    },
)
@limiter.limit(refresh_ip_limit)
def refresh(
    request: Request,
    response: Response,
    service: ServiceDep,
    settings: SettingsDep,
    token: RefreshCookie = None,
) -> LoginResponse | Response:
    """Uses the refresh cookie, issues a new one and a new access token. Reuse of a spent
    token ends the whole session family."""
    result = service.refresh(token)
    if result.issued is None:
        failure = error_response(
            request,
            ErrorCode.UNAUTHENTICATED,
            SIGNED_OUT,
            headers={"WWW-Authenticate": "Bearer"},
        )
        if result.clear_cookie:
            clear_refresh_cookie(failure, settings)
        return failure
    set_refresh_cookie(response, settings, result.issued.refresh_token)
    return _login_response(result.issued)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Sign out this session",
    dependencies=[CsrfDep],
)
def logout(
    response: Response, service: ServiceDep, settings: SettingsDep, token: RefreshCookie = None
) -> MessageResponse:
    service.logout(token)
    clear_refresh_cookie(response, settings)
    return MessageResponse(message="Signed out.")


@router.post("/logout-all", response_model=MessageResponse, summary="Sign out everywhere")
def logout_all(
    response: Response, ctx: OwnerCtx, service: ServiceDep, settings: SettingsDep
) -> MessageResponse:
    service.logout_all(ctx.tenant_id, ctx.user_id)
    clear_refresh_cookie(response, settings)
    return MessageResponse(message="Signed out everywhere.")


@router.get("/me", response_model=MeResponse, summary="Current user")
def me(ctx: OwnerCtx, session: SessionDep) -> MeResponse:
    row = session.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    ).first()
    if row is None:
        raise unauthenticated()
    user, tenant = row
    biz = session.get(BusinessSettings, ctx.tenant_id)
    summary = SettingsSummary(
        weekly_budget=_text(biz.weekly_budget) if biz else None,
        service_level=_text(biz.service_level) if biz else "0.950",
        default_lead_time_days=biz.default_lead_time_days if biz else 3,
        agents_enabled=biz.agents_enabled if biz else True,
    )
    return MeResponse(
        user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant), settings=summary
    )


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password and end other sessions",
)
def change_password(
    body: ChangePasswordRequest,
    ctx: OwnerCtx,
    service: ServiceDep,
    token: RefreshCookie = None,
) -> MessageResponse:
    service.change_password(
        ctx.tenant_id,
        ctx.user_id,
        body.current_password,
        body.new_password,
        current_refresh_token=token,
    )
    return MessageResponse(message="Password changed. Other devices were signed out.")


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=201,
    summary="Create a business and its owner (off by default)",
    responses={404: {"description": "Registration is switched off"}},
)
@limiter.limit(register_ip_limit)
def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    service: ServiceDep,
    settings: SettingsDep,
) -> LoginResponse:
    if not settings.allow_registration:
        raise AppError(ErrorCode.NOT_FOUND)
    issued = service.register(
        business_name=body.business_name,
        business_type=body.business_type,
        full_name=body.full_name,
        email=body.email,
        password=body.password,
    )
    set_refresh_cookie(response, settings, issued.refresh_token)
    return _login_response(issued)


class DemoProfile(BaseModel):
    key: str
    name: str


class AuthConfig(BaseModel):
    demo_login_enabled: bool
    demo_profiles: list[DemoProfile]


@router.get("/config", response_model=AuthConfig, summary="What the sign in page may offer")
def auth_config(session: SessionDep, settings: SettingsDep) -> AuthConfig:
    """Tells the sign in page whether to show the demo buttons. Names only, no ids."""
    if not settings.demo_login_enabled:
        return AuthConfig(demo_login_enabled=False, demo_profiles=[])
    rows = session.execute(
        select(Tenant.profile_key, Tenant.name)
        .where(
            Tenant.is_synthetic.is_(True),
            Tenant.is_active.is_(True),
            Tenant.profile_key.is_not(None),
        )
        .order_by(Tenant.created_at, Tenant.name)
    ).all()
    return AuthConfig(
        demo_login_enabled=True,
        demo_profiles=[DemoProfile(key=str(key), name=name) for key, name in rows],
    )


@router.post(
    "/demo-login",
    response_model=LoginResponse,
    summary="Sign in to a synthetic demo business (off by default)",
    responses={404: {"description": "Demo sign in is switched off or the profile is unknown"}},
)
@limiter.limit(demo_ip_limit)
def demo_login(
    request: Request,
    body: DemoLoginRequest,
    response: Response,
    service: ServiceDep,
    settings: SettingsDep,
) -> LoginResponse:
    if not settings.demo_login_enabled:
        raise AppError(ErrorCode.NOT_FOUND)
    issued = service.demo_login(body.profile_key)
    set_refresh_cookie(response, settings, issued.refresh_token)
    return _login_response(issued)
