"""Rate limits answer 429 with Retry-After in the standard envelope."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.ratelimit import reset_rate_limits
from app.main import create_app
from app.models.tenancy import User
from tests import factories
from tests.api.test_auth import API, CSRF, login, refresh_cookie
from tests.conftest import TwoTenants


def build_client(app: FastAPI, settings: Settings) -> TestClient:
    application = create_app(settings)
    application.dependency_overrides.update(app.dependency_overrides)
    return TestClient(application, raise_server_exceptions=False)


@pytest.fixture
def limited(app: FastAPI, test_settings: Settings) -> Iterator[TestClient]:
    """An app with limits switched on and small, sharing the test database session."""
    settings = test_settings.model_copy(
        update={
            "rate_limit_enabled": True,
            "rate_limit_login_ip": "5/minute",
            "rate_limit_login_email": "3/minute",
            "rate_limit_refresh_ip": "2/minute",
            "rate_limit_user": "3/minute",
        }
    )
    with build_client(app, settings) as client:
        yield client
    reset_rate_limits()


@pytest.fixture
def owner(db: Session) -> User:
    return factories.make_user(db, factories.make_tenant(db))


def assert_limited(response: Response) -> None:
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["request_id"]
    assert error["message"]


def test_login_is_limited_per_ip(limited: TestClient, owner: User) -> None:
    for i in range(5):
        response = login(limited, f"user{i}@nowhere.example.com", "wrong-password-123")
        assert response.status_code == 401
    assert_limited(login(limited, owner.email))


def test_login_is_limited_per_email(limited: TestClient, owner: User) -> None:
    for _ in range(3):
        assert login(limited, owner.email).status_code == 200
    assert_limited(login(limited, owner.email))
    # Another email from the same IP still gets through.
    assert login(limited, "other@nowhere.example.com", "wrong-password-123").status_code == 401


def test_refresh_is_limited_per_ip(limited: TestClient, owner: User) -> None:
    token = refresh_cookie(login(limited, owner.email))
    assert token
    for _ in range(2):
        limited.cookies.clear()
        response = limited.post(
            f"{API}/refresh", headers={**CSRF, "Cookie": f"backroom_rt={token}"}
        )
        token = refresh_cookie(response) or token
    limited.cookies.clear()
    third = limited.post(f"{API}/refresh", headers={**CSRF, "Cookie": f"backroom_rt={token}"})
    assert_limited(third)


def test_signed_in_users_have_a_general_limit(limited: TestClient, two_tenants: TwoTenants) -> None:
    a, b = two_tenants.a.headers, two_tenants.b.headers
    for _ in range(3):
        assert limited.get(f"{API}/me", headers=a).status_code == 200
    assert_limited(limited.get(f"{API}/me", headers=a))
    # The limit is per user, so tenant B is unaffected.
    assert limited.get(f"{API}/me", headers=b).status_code == 200


def test_registration_and_demo_login_are_limited(app: FastAPI, test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={
            "rate_limit_enabled": True,
            "allow_registration": True,
            "demo_login_enabled": True,
            "rate_limit_register_ip": "2/hour",
            "rate_limit_demo_ip": "2/hour",
        }
    )
    with build_client(app, settings) as client:
        for _ in range(2):
            demo = client.post(f"{API}/demo-login", json={"profile_key": "nope"})
            assert demo.status_code == 404
        assert_limited(client.post(f"{API}/demo-login", json={"profile_key": "nope"}))
        bad = {
            "business_name": "X Stores",
            "business_type": "fmcg",
            "full_name": "Ab Cd",
            "email": "a@b.example.com",
            "password": "short",
        }
        for _ in range(2):
            assert client.post(f"{API}/register", json=bad).status_code == 422
        assert_limited(client.post(f"{API}/register", json=bad))
    reset_rate_limits()
