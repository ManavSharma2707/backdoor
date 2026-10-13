"""Bearer authentication, tenant context and the role dependency, on a throwaway route."""

import uuid
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.config import Settings
from app.core.deps import OwnerCtx, require_role
from app.core.security import issue_access_token
from app.models.tenancy import Tenant, User
from tests import factories
from tests.conftest import TwoTenants

probe = APIRouter(prefix="/probe")


@probe.get("/whoami")
def whoami(ctx: OwnerCtx) -> dict[str, str]:
    return {"tenant_id": str(ctx.tenant_id), "user_id": str(ctx.user_id), "role": ctx.role}


@probe.get("/manager", dependencies=[Depends(require_role("manager"))])
def manager_only() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture
def probe_client(app: FastAPI) -> TestClient:
    app.include_router(probe, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


def token_for(settings: Settings, user: User, **overrides: object) -> dict[str, str]:
    values: dict[str, object] = {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "now": now_utc(),
    }
    values.update(overrides)
    token, _ = issue_access_token(settings, **values)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


def test_tenant_context_comes_from_the_token(
    probe_client: TestClient, two_tenants: TwoTenants
) -> None:
    for bundle in (two_tenants.a, two_tenants.b):
        body = probe_client.get("/api/v1/probe/whoami", headers=bundle.headers).json()
        assert body == {
            "tenant_id": str(bundle.tenant.id),
            "user_id": str(bundle.user.id),
            "role": "owner",
        }


def test_a_tenant_id_in_the_request_changes_nothing(
    probe_client: TestClient, two_tenants: TwoTenants
) -> None:
    response = probe_client.get(
        f"/api/v1/probe/whoami?tenant_id={two_tenants.b.tenant.id}",
        headers={**two_tenants.a.headers, "X-Tenant-Id": str(two_tenants.b.tenant.id)},
    )
    assert response.json()["tenant_id"] == str(two_tenants.a.tenant.id)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not.a.token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Token abc"},
    ],
)
def test_missing_or_malformed_credentials_are_401(
    probe_client: TestClient, headers: dict[str, str]
) -> None:
    response = probe_client.get("/api/v1/probe/whoami", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_expired_and_tampered_tokens_are_401(
    probe_client: TestClient, two_tenants: TwoTenants, test_settings: Settings
) -> None:
    user = two_tenants.a.user
    expired = token_for(test_settings, user, now=now_utc() - timedelta(hours=1))
    assert probe_client.get("/api/v1/probe/whoami", headers=expired).status_code == 401
    good = two_tenants.a.headers["Authorization"]
    tampered = {"Authorization": good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")}
    assert probe_client.get("/api/v1/probe/whoami", headers=tampered).status_code == 401


def test_token_for_the_wrong_tenant_is_401(
    probe_client: TestClient, two_tenants: TwoTenants, test_settings: Settings
) -> None:
    headers = token_for(test_settings, two_tenants.a.user, tenant_id=two_tenants.b.tenant.id)
    assert probe_client.get("/api/v1/probe/whoami", headers=headers).status_code == 401


def test_unknown_user_is_401(
    probe_client: TestClient, two_tenants: TwoTenants, test_settings: Settings
) -> None:
    headers = token_for(test_settings, two_tenants.a.user, user_id=uuid.uuid4())
    assert probe_client.get("/api/v1/probe/whoami", headers=headers).status_code == 401


def test_deactivated_user_or_tenant_is_locked_out_at_once(
    probe_client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    headers = two_tenants.a.headers
    assert probe_client.get("/api/v1/probe/whoami", headers=headers).status_code == 200
    two_tenants.a.user.is_active = False
    db.flush()
    assert probe_client.get("/api/v1/probe/whoami", headers=headers).status_code == 401
    two_tenants.a.user.is_active = True
    tenant = db.get(Tenant, two_tenants.a.tenant.id)
    assert tenant is not None
    tenant.is_active = False
    db.flush()
    assert probe_client.get("/api/v1/probe/whoami", headers=headers).status_code == 401


def test_role_dependency_uses_the_database_role(
    probe_client: TestClient, db: Session, test_settings: Settings
) -> None:
    tenant = factories.make_tenant(db)
    staff = factories.make_user(db, tenant, role="staff")
    manager = factories.make_user(db, tenant, role="manager")
    owner = factories.make_user(db, tenant, role="owner")
    for user, status in ((staff, 403), (manager, 200), (owner, 200)):
        headers = factories.auth_headers(test_settings, user)
        response = probe_client.get("/api/v1/probe/manager", headers=headers)
        assert response.status_code == status
    forbidden = probe_client.get(
        "/api/v1/probe/manager", headers=factories.auth_headers(test_settings, staff)
    )
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"
    # A staff user also cannot use an owner only route, whatever the token claims.
    staff_headers = factories.auth_headers(test_settings, staff)
    assert probe_client.get("/api/v1/probe/whoami", headers=staff_headers).status_code == 403


def test_require_role_rejects_an_unknown_role_name() -> None:
    with pytest.raises(ValueError, match="Unknown role"):
        require_role("superuser")
