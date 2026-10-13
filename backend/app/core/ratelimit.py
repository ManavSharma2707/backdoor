"""Rate limits (`security.md` sections 1 and 7, `api-spec.md` section 1).

Per IP limits on public endpoints use slowapi decorators. Limits keyed by something other than
the IP (the login email, the signed in user) use the same `limits` library through
`KeyedLimits`, because slowapi key functions only see the request. Storage is in memory, which
is correct for one instance. A second API instance needs a shared store such as Redis.
"""

import threading
import time
from dataclasses import dataclass

from cachetools import TTLCache
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.core.errors import AppError, error_response
from app.core.messages import ErrorCode

MAX_RETRY_AFTER_SECONDS = 3600
UNKNOWN_FAILURE_WINDOW_SECONDS = 15 * 60


@dataclass
class LimitConfig:
    """Limit strings read by the slowapi decorators at request time."""

    login_ip: str = "10/minute"
    refresh_ip: str = "30/minute"
    register_ip: str = "3/hour"
    demo_ip: str = "10/hour"


config = LimitConfig()
limiter = Limiter(key_func=get_remote_address, headers_enabled=False)


def login_ip_limit() -> str:
    return config.login_ip


def refresh_ip_limit() -> str:
    return config.refresh_ip


def register_ip_limit() -> str:
    return config.register_ip


def demo_ip_limit() -> str:
    return config.demo_ip


class KeyedLimits:
    """Moving window limits for keys that are not the client IP."""

    def __init__(self) -> None:
        self._storage = MemoryStorage()
        self._strategy = MovingWindowRateLimiter(self._storage)
        self.enabled = True

    def hit(self, scope: str, spec: str, *identifiers: str) -> int | None:
        """Count one hit. Returns None when allowed, else seconds until a retry can succeed."""
        if not self.enabled:
            return None
        item = parse(spec)
        if self._strategy.hit(item, scope, *identifiers):
            return None
        stats = self._strategy.get_window_stats(item, scope, *identifiers)
        return max(1, min(MAX_RETRY_AFTER_SECONDS, int(stats.reset_time - _now_seconds()) + 1))

    def check(self, scope: str, spec: str, *identifiers: str) -> None:
        retry_after = self.hit(scope, spec, *identifiers)
        if retry_after is not None:
            raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})

    def reset(self) -> None:
        self._storage.reset()


def _now_seconds() -> float:
    # The limits library stamps windows with the system clock, so compare against the same one.
    return time.time()


keyed_limits = KeyedLimits()


class UnknownEmailFailures:
    """Failure counts for emails that have no account.

    A real account locks after five failures. Mirroring that for unknown emails keeps a locked
    answer from proving that an account exists.
    """

    def __init__(self) -> None:
        self._counts: TTLCache[str, int] = TTLCache(
            maxsize=10_000, ttl=UNKNOWN_FAILURE_WINDOW_SECONDS
        )
        self._lock = threading.Lock()

    def count(self, key: str) -> int:
        with self._lock:
            return self._counts.get(key, 0)

    def add(self, key: str) -> int:
        with self._lock:
            value = self._counts.get(key, 0) + 1
            self._counts[key] = value
            return value

    def clear(self, key: str) -> None:
        with self._lock:
            self._counts.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


unknown_email_failures = UnknownEmailFailures()


def configure_rate_limits(settings: Settings) -> None:
    """Apply settings to the module level limiters. Called by `create_app`."""
    config.login_ip = settings.rate_limit_login_ip
    config.refresh_ip = settings.rate_limit_refresh_ip
    config.register_ip = settings.rate_limit_register_ip
    config.demo_ip = settings.rate_limit_demo_ip
    limiter.enabled = settings.rate_limit_enabled
    keyed_limits.enabled = settings.rate_limit_enabled
    reset_rate_limits()


def reset_rate_limits() -> None:
    limiter.reset()
    keyed_limits.reset()
    unknown_email_failures.reset()


def retry_after_seconds(exc: RateLimitExceeded) -> int:
    window = exc.limit.limit.get_expiry() if exc.limit is not None else 60
    return max(1, min(MAX_RETRY_AFTER_SECONDS, int(window)))


async def handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    """A slowapi rejection becomes the standard 429 envelope with `Retry-After`."""
    if not isinstance(exc, RateLimitExceeded):
        raise TypeError(f"Handler for RateLimitExceeded received {type(exc).__name__}")
    return error_response(
        request,
        ErrorCode.RATE_LIMITED,
        headers={"Retry-After": str(retry_after_seconds(exc))},
    )
