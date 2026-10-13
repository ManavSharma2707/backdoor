"""Password policy, hashing and access token validation."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    PASSWORD_MAX_LENGTH,
    PasswordPolicyError,
    PasswordService,
    TokenError,
    common_passwords,
    decode_access_token,
    hash_refresh_token,
    is_common_password,
    issue_access_token,
    new_refresh_token,
    validate_password,
)

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
USER = uuid.uuid4()
TENANT = uuid.uuid4()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        _env_file=None,  # type: ignore[call-arg]
    )


def make_token(settings: Settings, **overrides: object) -> str:
    claims: dict[str, object] = {
        "sub": str(USER),
        "tid": str(TENANT),
        "role": "owner",
        "jti": uuid.uuid4().hex,
        "iat": int(NOW.timestamp()),
        "nbf": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=15)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


# ------------------------------------------------------------------ password policy


def test_common_password_list_is_bundled_and_lowercase() -> None:
    words = common_passwords()
    assert len(words) > 400
    assert "password" in words
    assert all(word == word.lower() for word in words)


@pytest.mark.parametrize(
    "password",
    ["short", "elevenchars", "x" * (PASSWORD_MAX_LENGTH + 1), "has-a-nul-byte-\x00-in-it"],
)
def test_length_rules(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="at least 12 characters"):
        validate_password(password, email="a@b.example.com")


@pytest.mark.parametrize(
    "password",
    [
        "password1234",
        "Password12345!",
        "P@ssw0rd2026!!",
        "qwertyuiop12",
        "iloveyou2026",
        "aaaaaaaaaaaa",
        "abababababab",
        "123123123123",
    ],
)
def test_common_and_repetitive_passwords_are_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="avoid common passwords"):
        validate_password(password, email="owner@example.com")


@pytest.mark.parametrize(
    "password",
    ["owner@example.com", "OWNER@EXAMPLE.COM", "Shah Traders", "  shah traders  "],
)
def test_password_may_not_be_the_email_or_business_name(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="not your email or business name"):
        validate_password(password, email="owner@example.com", business_name="Shah Traders")


@pytest.mark.parametrize(
    "password",
    [
        "correct horse battery",
        "a-brand-new-passphrase",
        "Tractor-Mango-Lantern-9",
        "q7Zk-" + "-".join(["lantern", "orbit", "velvet"] * 5),
    ],
)
def test_long_unusual_passwords_pass_without_composition_rules(password: str) -> None:
    validate_password(password, email="owner@example.com", business_name="Shah Traders")


def test_is_common_password_ignores_edges_and_simple_swaps() -> None:
    assert is_common_password("Welcome123!")
    assert is_common_password("w3lc0me")
    assert not is_common_password("lantern-orbit-velvet")


# ------------------------------------------------------------------ hashing


def test_hash_verify_and_rehash(settings: Settings) -> None:
    service = PasswordService(settings)
    hashed = service.hash("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert service.verify(hashed, "correct horse battery")
    assert not service.verify(hashed, "wrong horse battery")
    assert not service.needs_rehash(hashed)

    stronger = PasswordService(settings.model_copy(update={"argon2_time_cost": 2}))
    assert stronger.needs_rehash(hashed)


def test_verify_treats_a_malformed_stored_hash_as_a_mismatch(settings: Settings) -> None:
    service = PasswordService(settings)
    assert not service.verify("not-a-real-hash", "whatever")
    assert not service.needs_rehash("not-a-real-hash")


def test_production_hash_parameters_follow_the_spec() -> None:
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    hashed = PasswordService(defaults).hash("correct horse battery")
    assert "m=65536,t=3,p=2" in hashed


def test_refresh_tokens_are_random_and_only_hashes_are_derived() -> None:
    raw_a, hash_a = new_refresh_token()
    raw_b, _ = new_refresh_token()
    assert raw_a != raw_b
    assert len(raw_a) >= 43  # 32 random bytes, url safe base64
    assert hash_a == hash_refresh_token(raw_a)
    assert len(hash_a) == 64


# ------------------------------------------------------------------ access tokens


def test_access_token_round_trip(settings: Settings) -> None:
    token, expires_in = issue_access_token(
        settings, user_id=USER, tenant_id=TENANT, role="owner", now=NOW
    )
    assert expires_in == 900
    claims = decode_access_token(settings, token, now=NOW + timedelta(minutes=1))
    assert (claims.user_id, claims.tenant_id, claims.role) == (USER, TENANT, "owner")
    payload = jwt.decode(token, options={"verify_signature": False})
    assert set(payload) == {"sub", "tid", "role", "jti", "iat", "nbf", "exp", "iss", "aud"}
    assert payload["iss"] == "backroom"
    assert payload["aud"] == "backroom-web"


def test_expired_token_is_refused_after_the_leeway(settings: Settings) -> None:
    token = make_token(settings)
    decode_access_token(settings, token, now=NOW + timedelta(minutes=15, seconds=9))
    with pytest.raises(TokenError, match="ExpiredSignature"):
        decode_access_token(settings, token, now=NOW + timedelta(minutes=15, seconds=10))


def test_token_from_the_future_is_refused(settings: Settings) -> None:
    token = make_token(settings)
    with pytest.raises(TokenError, match="ImmatureSignature"):
        decode_access_token(settings, token, now=NOW - timedelta(minutes=5))


def test_tampered_token_is_refused(settings: Settings) -> None:
    token = make_token(settings)
    header, payload, signature = token.split(".")
    other_claims = {
        **jwt.decode(token, options={"verify_signature": False}),
        "tid": str(uuid.uuid4()),
    }
    forged = jwt.encode(other_claims, "some-other-secret-of-sufficient-length-1234", "HS256")
    swapped = f"{header}.{payload}.{signature[:-2]}AA"
    for bad in (swapped, forged, "not.a.jwt", ""):
        with pytest.raises(TokenError):
            decode_access_token(settings, bad, now=NOW)


def test_algorithm_none_and_other_algorithms_are_refused(settings: Settings) -> None:
    claims = jwt.decode(make_token(settings), options={"verify_signature": False})
    unsigned = jwt.encode(claims, None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(settings, unsigned, now=NOW)
    hs512 = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS512")
    with pytest.raises(TokenError):
        decode_access_token(settings, hs512, now=NOW)


@pytest.mark.parametrize("claim", ["sub", "tid", "role", "jti", "iat", "nbf", "exp", "iss", "aud"])
def test_every_claim_is_required(settings: Settings, claim: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(settings, make_token(settings, **{claim: None}), now=NOW)


@pytest.mark.parametrize(
    "override",
    [{"iss": "someone-else"}, {"aud": "another-app"}, {"sub": "not-a-uuid"}, {"tid": 7}],
)
def test_wrong_issuer_audience_or_identity_is_refused(
    settings: Settings, override: dict[str, object]
) -> None:
    with pytest.raises(TokenError):
        decode_access_token(settings, make_token(settings, **override), now=NOW)
