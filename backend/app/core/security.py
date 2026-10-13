"""Passwords and tokens (`security.md` section 1).

Passwords: argon2id, a length based policy and a bundled list of common passwords.
Access tokens: HS256 JWTs with every claim required, validated against our own clock so tests
can move time. Refresh tokens: opaque random values of which only the SHA-256 hash is stored.
"""

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

ALGORITHM = "HS256"
LEEWAY_SECONDS = 10
REQUIRED_CLAIMS = ("sub", "tid", "role", "jti", "iat", "nbf", "exp", "iss", "aud")

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
PASSWORD_POLICY_MESSAGE = (
    f"Use at least {PASSWORD_MIN_LENGTH} characters and avoid common passwords."
)
COMMON_PASSWORDS_FILE = Path(__file__).resolve().parent.parent / "assets" / "common_passwords.txt"

_LEET = str.maketrans({"@": "a", "4": "a", "0": "o", "3": "e", "$": "s", "5": "s", "!": "i"})
_EDGE_NOISE = string.digits + string.punctuation + string.whitespace


class PasswordPolicyError(ValueError):
    """The password does not meet the policy. The message is safe to show."""


class TokenError(Exception):
    """An access token failed validation. The reason is for logs, never for the client."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@lru_cache
def common_passwords() -> frozenset[str]:
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def _is_repetitive(password: str) -> bool:
    """One character repeated, or a short block repeated, such as `abababababab`."""
    for size in range(1, len(password) // 3 + 1):
        block = password[:size]
        if len(password) % size == 0 and block * (len(password) // size) == password:
            return True
    return False


def is_common_password(password: str) -> bool:
    """True for a listed password, or one that is a listed word with digits or symbols on
    the edges or common letter swaps (`P@ssword2026!`)."""
    common = common_passwords()
    lowered = password.lower()
    candidates = {lowered, lowered.translate(_LEET)}
    for value in tuple(candidates):
        candidates.add(value.strip(_EDGE_NOISE))
    return any(candidate in common for candidate in candidates if candidate)


def validate_password(password: str, *, email: str, business_name: str | None = None) -> None:
    """Raise `PasswordPolicyError` when `password` breaks the policy.

    No composition rules: length matters more. The password must not be the email address
    or the business name, nor a common password.
    """
    if (
        len(password) < PASSWORD_MIN_LENGTH
        or len(password) > PASSWORD_MAX_LENGTH
        or "\x00" in password
    ):
        raise PasswordPolicyError(PASSWORD_POLICY_MESSAGE)
    lowered = password.strip().lower()
    forbidden = {email.strip().lower()}
    if "@" in email:
        forbidden.add(email.strip().lower().split("@", 1)[0])
    if business_name:
        forbidden.add(business_name.strip().lower())
    if lowered in forbidden:
        raise PasswordPolicyError("Choose a password that is not your email or business name.")
    if is_common_password(password) or _is_repetitive(lowered):
        raise PasswordPolicyError(PASSWORD_POLICY_MESSAGE)


class PasswordService:
    """argon2id hashing with the parameters from settings.

    `verify_unknown` hashes against a dummy value so a login for an unknown email costs as much
    as one for a known email.
    """

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
            hash_len=32,
            salt_len=16,
        )
        self._dummy_hash: str | None = None

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False

    def verify_unknown(self, password: str) -> None:
        """Spend the time of one verification and discard the answer."""
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(24))
        self.verify(self._dummy_hash, password)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """A fresh opaque token and its stored hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    jti: str
    expires_at: datetime


def issue_access_token(
    settings: Settings, *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str, now: datetime
) -> tuple[str, int]:
    """Sign an access token. Returns the token and its lifetime in seconds."""
    lifetime = timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(settings: Settings, token: str, *, now: datetime) -> AccessClaims:
    """Validate signature, algorithm, issuer, audience and every claim, or raise `TokenError`.

    PyJWT checks times against the system clock, so those checks are switched off here and
    done below against `now`.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": list(REQUIRED_CLAIMS),
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise TokenError(type(exc).__name__) from exc

    stamp = now.timestamp()
    try:
        expires = float(claims["exp"])
        not_before = float(claims["nbf"])
        issued = float(claims["iat"])
        user_id = uuid.UUID(str(claims["sub"]))
        tenant_id = uuid.UUID(str(claims["tid"]))
    except (TypeError, ValueError) as exc:
        raise TokenError("MalformedClaim") from exc
    if expires + LEEWAY_SECONDS <= stamp:
        raise TokenError("ExpiredSignature")
    if not_before - LEEWAY_SECONDS > stamp or issued - LEEWAY_SECONDS > stamp:
        raise TokenError("ImmatureSignature")
    role = claims["role"]
    jti = claims["jti"]
    if not isinstance(role, str) or not isinstance(jti, str):
        raise TokenError("MalformedClaim")
    return AccessClaims(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        jti=jti,
        expires_at=datetime.fromtimestamp(expires, tz=now.tzinfo),
    )
