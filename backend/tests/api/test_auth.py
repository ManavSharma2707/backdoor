"""Auth endpoints: sign in, lockout, refresh rotation, reuse, grace, sign out, password change."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock, use_clock
from app.core.config import Settings
from app.core.security import PasswordService
from app.models.ops import AuditLog
from app.models.tenancy import RefreshToken, Tenant, User
from tests import factories
from tests.factories import TEST_PASSWORD

API = "/api/v1/auth"
CSRF = {"X-Requested-With": "backroom"}
LOGIN_FAILED = "Email or password is not right."
START = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> Iterator[FakeClock]:
    with use_clock(FakeClock(START)) as fake:
        yield fake  # type: ignore[misc]


@pytest.fixture
def owner(db: Session) -> User:
    tenant = factories.make_tenant(db, name="Shah Traders")
    return factories.make_user(db, tenant, email="owner@shah-traders.example.com")


def login(client: TestClient, email: str, password: str = TEST_PASSWORD):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/login", json={"email": email, "password": password})


def refresh_cookie(response) -> str | None:  # type: ignore[no-untyped-def]
    """The raw refresh token set by a response, or None when it was cleared."""
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        if "backroom_rt" in cookie and cookie["backroom_rt"].value:
            return cookie["backroom_rt"].value
    return None


def refresh(client: TestClient, token: str, **headers: str):  # type: ignore[no-untyped-def]
    client.cookies.clear()
    return client.post(
        f"{API}/refresh", headers={**CSRF, "Cookie": f"backroom_rt={token}", **headers}
    )


def bearer(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def audit_actions(db: Session, tenant_id) -> list[str]:  # type: ignore[no-untyped-def]
    rows = db.execute(
        select(AuditLog.action).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id)
    )
    return list(rows.scalars())


# --------------------------------------------------------------------------- sign in


def test_login_returns_token_user_tenant_and_cookie(client: TestClient, owner: User) -> None:
    response = login(client, owner.email)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["user"] == {
        "id": str(owner.id),
        "email": owner.email,
        "full_name": "Test Owner",
        "role": "owner",
    }
    assert body["tenant"]["name"] == "Shah Traders"
    assert body["tenant"]["is_synthetic"] is True
    assert response.headers["cache-control"] == "no-store"


def test_login_cookie_attributes(client: TestClient, owner: User) -> None:
    response = login(client, owner.email)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("backroom_rt=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert f"Max-Age={14 * 24 * 3600}" in cookie
    # Local http: the Secure flag follows COOKIE_SECURE, which is off in the test settings.
    assert "Secure" not in cookie


def test_login_cookie_is_secure_when_settings_say_so(
    app,
    db: Session,
    test_settings: Settings,
    owner: User,  # type: ignore[no-untyped-def]
) -> None:
    from app.main import create_app

    secure_app = create_app(test_settings.model_copy(update={"cookie_secure": True}))
    secure_app.dependency_overrides.update(app.dependency_overrides)
    with TestClient(secure_app) as client:
        cookie = login(client, owner.email).headers["set-cookie"]
    assert "Secure" in cookie


def test_only_the_hash_of_the_refresh_token_is_stored(
    client: TestClient, db: Session, owner: User
) -> None:
    response = login(client, owner.email)
    raw = refresh_cookie(response)
    assert raw is not None
    row = db.execute(select(RefreshToken).where(RefreshToken.user_id == owner.id)).scalar_one()
    assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in row.token_hash
    assert row.expires_at - row.issued_at == timedelta(days=14)
    assert row.rotated_at is None
    assert row.revoked_at is None


def test_login_normalises_the_email(client: TestClient, owner: User) -> None:
    assert login(client, f"  {owner.email.upper()} ").status_code == 200


def test_login_audit_row_has_no_secret(client: TestClient, db: Session, owner: User) -> None:
    login(client, owner.email)
    row = db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == owner.tenant_id, AuditLog.action == "auth.login.success"
        )
    ).scalar_one()
    assert row.user_id == owner.id
    assert row.request_id
    assert TEST_PASSWORD not in str(row.before) + str(row.after)


def test_wrong_password_and_unknown_email_give_the_same_answer(
    client: TestClient, db: Session, owner: User
) -> None:
    wrong = login(client, owner.email, "not-the-password-at-all")
    unknown = login(client, "nobody@nowhere.example.com", "not-the-password-at-all")
    assert wrong.status_code == unknown.status_code == 401
    for response in (wrong, unknown):
        error = response.json()["error"]
        assert error["code"] == "UNAUTHENTICATED"
        assert error["message"] == LOGIN_FAILED
        assert error["request_id"]
    actions = audit_actions(db, owner.tenant_id)
    assert actions == ["auth.login.failure"]


def test_failure_audit_stores_a_hash_of_the_email_never_the_email(
    client: TestClient, db: Session
) -> None:
    login(client, "nobody@nowhere.example.com", "whatever-it-is-12")
    row = (
        db.execute(select(AuditLog).where(AuditLog.action == "auth.login.failure"))
        .scalars()
        .first()
    )
    assert row is not None
    assert "nobody" not in str(row.after)
    assert len(row.after["email_hash"]) == 16


def test_every_login_path_runs_exactly_one_password_verification(
    client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = PasswordHasher.verify

    def spy(self: PasswordHasher, hash: str, password: str | bytes) -> bool:
        calls.append(hash[:12])
        return original(self, hash, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)

    login(client, owner.email)  # success
    assert len(calls) == 1
    calls.clear()
    login(client, owner.email, "wrong-password-123")  # wrong password
    assert len(calls) == 1
    calls.clear()
    login(client, "nobody@nowhere.example.com", "wrong-password-123")  # unknown email
    assert len(calls) == 1


def test_inactive_user_and_inactive_tenant_cannot_sign_in(
    client: TestClient, db: Session, owner: User
) -> None:
    owner.is_active = False
    db.flush()
    assert login(client, owner.email).status_code == 401
    owner.is_active = True
    tenant = db.get(Tenant, owner.tenant_id)
    assert tenant is not None
    tenant.is_active = False
    db.flush()
    response = login(client, owner.email)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == LOGIN_FAILED


def test_login_rehashes_when_the_parameters_changed(
    client: TestClient, db: Session, owner: User
) -> None:
    weaker = Settings(
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        _env_file=None,  # type: ignore[call-arg]
    )
    stronger = Settings(
        argon2_time_cost=2,
        argon2_memory_cost_kib=16,
        argon2_parallelism=1,
        _env_file=None,  # type: ignore[call-arg]
    )
    owner.password_hash = PasswordService(weaker).hash(TEST_PASSWORD)
    db.flush()
    old_hash = owner.password_hash
    assert PasswordService(stronger).needs_rehash(old_hash)

    client.app.state.password_service = PasswordService(stronger)  # type: ignore[attr-defined]
    assert login(client, owner.email).status_code == 200
    db.refresh(owner)
    assert owner.password_hash != old_hash
    assert not PasswordService(stronger).needs_rehash(owner.password_hash)
    assert PasswordService(stronger).verify(owner.password_hash, TEST_PASSWORD)


# --------------------------------------------------------------------------- lockout


def test_five_failures_lock_the_account_for_fifteen_minutes(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    for _ in range(4):
        response = login(client, owner.email, "wrong-password-123")
        assert "retry-after" not in response.headers
    fifth = login(client, owner.email, "wrong-password-123")
    assert fifth.status_code == 401
    assert fifth.headers["retry-after"] == str(15 * 60)
    db.refresh(owner)
    assert owner.failed_login_count == 5
    assert owner.locked_until == START + timedelta(minutes=15)
    assert "auth.lockout" in audit_actions(db, owner.tenant_id)

    # The right password is refused while locked, with the same generic message.
    clock.advance(timedelta(minutes=5))
    locked = login(client, owner.email)
    assert locked.status_code == 401
    assert locked.json()["error"]["message"] == LOGIN_FAILED
    assert int(locked.headers["retry-after"]) == 10 * 60 + 1

    clock.advance(timedelta(minutes=10, seconds=1))
    assert login(client, owner.email).status_code == 200
    db.refresh(owner)
    assert owner.failed_login_count == 0
    assert owner.locked_until is None


def test_failures_older_than_the_window_do_not_add_up(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    for _ in range(4):
        login(client, owner.email, "wrong-password-123")
    clock.advance(timedelta(minutes=16))
    login(client, owner.email, "wrong-password-123")
    db.refresh(owner)
    assert owner.failed_login_count == 1
    assert owner.locked_until is None


def test_a_good_login_resets_the_failure_count(
    client: TestClient, db: Session, owner: User
) -> None:
    for _ in range(3):
        login(client, owner.email, "wrong-password-123")
    assert login(client, owner.email).status_code == 200
    db.refresh(owner)
    assert owner.failed_login_count == 0


def test_unknown_emails_lock_the_same_way_so_a_lock_proves_nothing(
    client: TestClient, clock: FakeClock
) -> None:
    for _ in range(4):
        response = login(client, "ghost@nowhere.example.com", "wrong-password-123")
        assert "retry-after" not in response.headers
    fifth = login(client, "ghost@nowhere.example.com", "wrong-password-123")
    assert fifth.headers["retry-after"] == str(15 * 60)
    assert fifth.json()["error"]["message"] == LOGIN_FAILED


def test_login_validation_error_is_an_envelope(client: TestClient) -> None:
    response = client.post(f"{API}/login", json={"email": "not-an-email", "password": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- refresh


def test_refresh_rotates_and_the_new_access_token_works(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    first = refresh_cookie(login(client, owner.email))
    assert first
    clock.advance(timedelta(seconds=30))
    response = refresh(client, first)
    assert response.status_code == 200
    second = refresh_cookie(response)
    assert second
    assert second != first
    assert client.get(f"{API}/me", headers=bearer(response)).status_code == 200

    old = db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(first.encode()).hexdigest()
        )
    ).scalar_one()
    new = db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(second.encode()).hexdigest()
        )
    ).scalar_one()
    assert old.rotated_at is not None
    assert old.replaced_by_id == new.id
    assert new.family_id == old.family_id
    assert new.rotated_at is None


def test_refresh_requires_the_csrf_header(client: TestClient, owner: User) -> None:
    token = refresh_cookie(login(client, owner.email))
    assert token
    client.cookies.clear()
    response = client.post(f"{API}/refresh", headers={"Cookie": f"backroom_rt={token}"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_refresh_refuses_a_foreign_origin_and_accepts_ours(client: TestClient, owner: User) -> None:
    token = refresh_cookie(login(client, owner.email))
    assert token
    assert refresh(client, token, Origin="https://evil.example.org").status_code == 403
    assert refresh(client, token, Origin="http://localhost:5173").status_code == 200


def test_refresh_without_a_cookie_is_401(client: TestClient) -> None:
    client.cookies.clear()
    response = client.post(f"{API}/refresh", headers=CSRF)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_refresh_token_is_401_and_clears_the_cookie(client: TestClient) -> None:
    response = refresh(client, "x" * 43)
    assert response.status_code == 401
    assert (
        'backroom_rt=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )


def test_reusing_a_rotated_token_revokes_the_whole_family(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    first = refresh_cookie(login(client, owner.email))
    assert first
    clock.advance(timedelta(seconds=1))
    second_response = refresh(client, first)
    second = refresh_cookie(second_response)
    assert second

    # Outside the grace window the old token can only be a replay.
    clock.advance(timedelta(seconds=11))
    replay = refresh(client, first)
    assert replay.status_code == 401
    assert "Max-Age=0" in replay.headers["set-cookie"]
    assert "auth.refresh_reuse" in audit_actions(db, owner.tenant_id)

    # The family is dead, including the newest token.
    assert refresh(client, second).status_code == 401
    revoked = db.execute(
        select(RefreshToken.revoked_reason).where(RefreshToken.user_id == owner.id)
    ).scalars()
    assert set(revoked) == {"reuse_detected"}


def test_grace_window_refuses_without_revoking_the_family(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    first = refresh_cookie(login(client, owner.email))
    assert first
    clock.advance(timedelta(seconds=1))
    second = refresh_cookie(refresh(client, first))
    assert second

    clock.advance(timedelta(seconds=5))
    racing = refresh(client, first)
    assert racing.status_code == 401
    assert "auth.refresh_reuse" not in audit_actions(db, owner.tenant_id)
    # The winner's session is untouched.
    assert refresh(client, second).status_code == 200


def test_grace_window_does_not_apply_once_the_successor_was_used(
    client: TestClient, db: Session, owner: User, clock: FakeClock
) -> None:
    first = refresh_cookie(login(client, owner.email))
    assert first
    clock.advance(timedelta(seconds=1))
    second = refresh_cookie(refresh(client, first))
    assert second
    clock.advance(timedelta(seconds=1))
    assert refresh(client, second).status_code == 200  # the successor is now spent
    clock.advance(timedelta(seconds=1))
    assert refresh(client, first).status_code == 401
    assert "auth.refresh_reuse" in audit_actions(db, owner.tenant_id)


def test_refresh_token_expires_after_fourteen_days(
    client: TestClient, owner: User, clock: FakeClock
) -> None:
    token = refresh_cookie(login(client, owner.email))
    assert token
    clock.advance(timedelta(days=14, seconds=1))
    assert refresh(client, token).status_code == 401


def test_refresh_fails_for_a_deactivated_user(client: TestClient, db: Session, owner: User) -> None:
    token = refresh_cookie(login(client, owner.email))
    assert token
    owner.is_active = False
    db.flush()
    assert refresh(client, token).status_code == 401


# --------------------------------------------------------------------------- sign out


def test_logout_revokes_the_session_and_clears_the_cookie(
    client: TestClient, db: Session, owner: User
) -> None:
    token = refresh_cookie(login(client, owner.email))
    assert token
    client.cookies.clear()
    response = client.post(f"{API}/logout", headers={**CSRF, "Cookie": f"backroom_rt={token}"})
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "auth.logout" in audit_actions(db, owner.tenant_id)
    assert refresh(client, token).status_code == 401


def test_logout_needs_the_csrf_header_but_not_a_cookie(client: TestClient) -> None:
    assert client.post(f"{API}/logout").status_code == 403
    assert client.post(f"{API}/logout", headers=CSRF).status_code == 200


def test_logout_all_ends_every_session(client: TestClient, db: Session, owner: User) -> None:
    first = login(client, owner.email)
    second = login(client, owner.email)
    tokens = [refresh_cookie(first), refresh_cookie(second)]
    response = client.post(f"{API}/logout-all", headers=bearer(first))
    assert response.status_code == 200
    assert "auth.logout_all" in audit_actions(db, owner.tenant_id)
    for token in tokens:
        assert token
        assert refresh(client, token).status_code == 401


def test_logout_all_needs_a_bearer_token(client: TestClient) -> None:
    assert client.post(f"{API}/logout-all").status_code == 401


# --------------------------------------------------------------------------- me


def test_me_returns_user_tenant_and_settings_summary(client: TestClient, owner: User) -> None:
    response = client.get(f"{API}/me", headers=bearer(login(client, owner.email)))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == owner.email
    assert body["tenant"]["slug"].startswith("tenant-")
    assert body["settings"] == {
        "weekly_budget": None,
        "service_level": "0.950",
        "default_lead_time_days": 3,
        "agents_enabled": True,
    }


# --------------------------------------------------------------------------- password change


def test_change_password_revokes_other_sessions_and_keeps_this_one(
    client: TestClient, db: Session, owner: User
) -> None:
    this_session = login(client, owner.email)
    other = refresh_cookie(login(client, owner.email))
    mine = refresh_cookie(this_session)
    assert other
    assert mine
    client.cookies.clear()
    new_password = "a-brand-new-passphrase-2026"
    response = client.post(
        f"{API}/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": new_password},
        headers={**bearer(this_session), "Cookie": f"backroom_rt={mine}"},
    )
    assert response.status_code == 200
    assert "auth.password_change" in audit_actions(db, owner.tenant_id)

    assert refresh(client, other).status_code == 401
    assert refresh(client, mine).status_code == 200
    assert login(client, owner.email).status_code == 401
    assert login(client, owner.email, new_password).status_code == 200


def test_change_password_without_a_cookie_ends_every_session(
    client: TestClient, owner: User
) -> None:
    session = login(client, owner.email)
    token = refresh_cookie(session)
    assert token
    client.cookies.clear()
    response = client.post(
        f"{API}/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-passphrase-2026"},
        headers=bearer(session),
    )
    assert response.status_code == 200
    assert refresh(client, token).status_code == 401


def test_change_password_checks_the_current_password_and_counts_failures(
    client: TestClient, db: Session, owner: User
) -> None:
    session = login(client, owner.email)
    response = client.post(
        f"{API}/change-password",
        json={"current_password": "not-the-current-one", "new_password": "a-brand-new-passphrase"},
        headers=bearer(session),
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"][0]["field"] == "current_password"
    db.refresh(owner)
    assert owner.failed_login_count == 1


@pytest.mark.parametrize(
    ("new_password", "field"),
    [
        ("short-one", "new_password"),
        ("password12345", "new_password"),
        ("owner@shah-traders.example.com", "new_password"),
        ("Shah Traders", "new_password"),
        (TEST_PASSWORD, "new_password"),
    ],
)
def test_change_password_rejects_weak_or_unchanged_passwords(
    client: TestClient, owner: User, new_password: str, field: str
) -> None:
    session = login(client, owner.email)
    response = client.post(
        f"{API}/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": new_password},
        headers=bearer(session),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field
    assert login(client, owner.email).status_code == 200  # the old password still works


# --------------------------------------------------------------------------- flags


def test_registration_and_demo_login_are_off_by_default(client: TestClient) -> None:
    register = client.post(
        f"{API}/register",
        json={
            "business_name": "Patel Stores",
            "business_type": "fmcg",
            "full_name": "Asha Patel",
            "email": "asha@patel-stores.example.com",
            "password": "a-long-enough-passphrase",
        },
    )
    assert register.status_code == 404
    assert register.json()["error"]["code"] == "NOT_FOUND"
    demo = client.post(f"{API}/demo-login", json={"profile_key": "fmcg_a"})
    assert demo.status_code == 404


@pytest.fixture
def open_client(app, test_settings: Settings, db: Session) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.main import create_app

    flagged = create_app(
        test_settings.model_copy(update={"allow_registration": True, "demo_login_enabled": True})
    )
    flagged.dependency_overrides.update(app.dependency_overrides)
    with TestClient(flagged, raise_server_exceptions=False) as test_client:
        yield test_client


def test_registration_creates_a_tenant_and_a_working_owner(
    open_client: TestClient, db: Session
) -> None:
    payload = {
        "business_name": "Patel Stores",
        "business_type": "fmcg",
        "full_name": "Asha Patel",
        "email": "Asha@Patel-Stores.example.com",
        "password": "a-long-enough-passphrase",
    }
    response = open_client.post(f"{API}/register", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["tenant"]["is_synthetic"] is False
    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "asha@patel-stores.example.com"
    assert refresh_cookie(response)
    assert (
        login(open_client, "asha@patel-stores.example.com", payload["password"]).status_code == 200
    )
    # Second sign up with the same email conflicts.
    again = open_client.post(f"{API}/register", json=payload)
    assert again.status_code == 409


def test_registration_applies_the_password_policy(open_client: TestClient) -> None:
    response = open_client.post(
        f"{API}/register",
        json={
            "business_name": "Patel Stores",
            "business_type": "medical",
            "full_name": "Asha Patel",
            "email": "asha@patel-stores.example.com",
            "password": "Patel Stores",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "password"


def test_demo_login_works_for_synthetic_tenants_only(open_client: TestClient, db: Session) -> None:
    demo = factories.make_tenant(db, profile_key="fmcg_a", is_synthetic=True)
    factories.make_user(db, demo)
    real = factories.make_tenant(db, profile_key="real_shop", is_synthetic=False)
    factories.make_user(db, real)

    ok = open_client.post(f"{API}/demo-login", json={"profile_key": "fmcg_a"})
    assert ok.status_code == 200
    assert ok.json()["tenant"]["id"] == str(demo.id)
    assert refresh_cookie(ok)
    refused = open_client.post(f"{API}/demo-login", json={"profile_key": "real_shop"})
    assert refused.status_code == 404
    unknown = open_client.post(f"{API}/demo-login", json={"profile_key": "nothing"})
    assert unknown.status_code == 404
