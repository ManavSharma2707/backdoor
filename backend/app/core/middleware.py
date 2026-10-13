"""Pure ASGI middleware: request id, access log and security headers.

Written as plain ASGI (not `BaseHTTPMiddleware`) so streaming responses such as the chat SSE
stream are never buffered and context variables survive into sync endpoints.
"""

import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import REQUEST_ID_STATE_KEY, handle_unexpected_error
from app.core.logging import bind_request_context, clear_request_context, get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Responses that carry session or report data must never be cached (security.md section 3).
NO_STORE_PREFIXES = ("/api/v1/auth", "/api/v1/reports", "/api/v1/exports")

log = get_logger(__name__)


def route_template(scope: Scope) -> str | None:
    """The matched route with its mount prefix, for example `/api/v1/products/{product_id}`.

    FastAPI mounts included routers lazily, so `scope["route"].path` is relative to the
    prefix. Find the prefix by matching the route against the tail of the real path.
    """
    route = scope.get("route")
    path_format = getattr(route, "path_format", None)
    path_regex = getattr(route, "path_regex", None)
    if path_format is None or path_regex is None:
        return None
    path: str = scope.get("path", "")
    for start in range(len(path) + 1):
        if path_regex.match(path[start:]):
            return str(path[:start] + path_format)
    return str(path_format)


class UnhandledErrorMiddleware:
    """Turn any unexpected exception into the 500 envelope, innermost in the stack.

    Starlette would otherwise answer from `ServerErrorMiddleware`, outside every other
    middleware, so the response would lack the request id, security headers and CORS headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            if started:
                raise
            response = await handle_unexpected_error(Request(scope), exc)
            await response(scope, receive, send)


class RequestIdMiddleware:
    """Assign a request id, bind it to the log context and write one access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = MutableHeaders(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})[REQUEST_ID_STATE_KEY] = request_id
        bind_request_context(request_id=request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log.info(
                "request.completed",
                method=scope.get("method"),
                path=scope.get("path"),
                route=route_template(scope),
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            clear_request_context()


class SecurityHeadersMiddleware:
    """Headers from `security.md` section 3. HSTS only when not running locally."""

    def __init__(self, app: ASGIApp, *, enable_hsts: bool) -> None:
        self.app = app
        self.enable_hsts = enable_hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                if self.enable_hsts:
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if path.startswith(NO_STORE_PREFIXES):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
