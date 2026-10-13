"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.core.ratelimit import configure_rate_limits, handle_rate_limit_exceeded
from app.core.security import PasswordService
from app.schemas.common import ErrorEnvelope
from app.version import APP_VERSION

API_PREFIX = "/api/v1"
# Starlette defaults to 40 worker threads. Render free has 512 MB, so keep it small.
THREAD_LIMIT = 10

DESCRIPTION = """
Backroom API. Retail inventory and procurement for small shops, built around one weekly
buying plan.

All data in the demo is synthetic. Money and quantities are strings. Every error uses the
same envelope: `{"error": {"code", "message", "details", "request_id"}}`.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "auth", "description": "Sign in, refresh token rotation, sign out and password."},
    {"name": "settings", "description": "Business settings that shape the weekly plan."},
    {"name": "catalogue", "description": "Categories, products, prices, equivalents, GST rates."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    log = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        anyio.to_thread.current_default_thread_limiter().total_tokens = THREAD_LIMIT
        log.info("app.start", env=settings.app_env)
        yield
        dispose_engine()
        log.info("app.stop")

    app = FastAPI(
        title="Backroom API",
        version=APP_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=lifespan,
        responses={
            422: {"model": ErrorEnvelope, "description": "Validation error"},
            500: {"model": ErrorEnvelope, "description": "Unexpected error"},
        },
    )
    install_error_handlers(app)
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)
    app.state.settings = settings
    app.state.password_service = PasswordService(settings)
    configure_rate_limits(settings)

    # Each call wraps the previous ones, so the last added runs outermost. Request id wraps
    # everything, so every response has one, including a 500 from an unexpected exception.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Requested-With",
            REQUEST_ID_HEADER,
        ],
        expose_headers=[REQUEST_ID_HEADER, "Idempotent-Replay", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.app_env != "local")
    app.add_middleware(RequestIdMiddleware)

    app.include_router(api_router, prefix=API_PREFIX)
    # Convenience aliases at the root for uptime checks that cannot use the versioned path.
    app.include_router(health.router, include_in_schema=False)
    return app


app = create_app()
