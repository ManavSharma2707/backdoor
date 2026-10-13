"""The error envelope and the exception handlers that produce it.

One shape for every failure (`api-spec.md` section 1). Stack traces, SQL and internal ids never
leave the process.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.messages import DEFAULT_MESSAGES, STATUS_BY_CODE, ErrorCode
from app.core.text import humanize_text
from app.schemas.common import ErrorBody, ErrorDetail, ErrorEnvelope

log = get_logger(__name__)

REQUEST_ID_STATE_KEY = "request_id"

HTTP_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


class AppError(Exception):
    """Base class for domain errors. The status code follows from the error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: Sequence[ErrorDetail] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.status_code = STATUS_BY_CODE[code]
        self.message = message or DEFAULT_MESSAGES[code]
        self.details = list(details or [])
        self.headers = dict(headers or {})
        super().__init__(f"{code}: {self.message}")


def request_id_of(request: Request) -> str | None:
    value = request.scope.get("state", {}).get(REQUEST_ID_STATE_KEY)
    return str(value) if value else None


def error_response(
    request: Request,
    code: ErrorCode,
    message: str | None = None,
    *,
    status_code: int | None = None,
    details: Sequence[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code.value,
            message=humanize_text(message or DEFAULT_MESSAGES[code]),
            details=list(details or []),
            request_id=request_id_of(request),
        )
    )
    return JSONResponse(
        status_code=status_code or STATUS_BY_CODE[code],
        content=envelope.model_dump(mode="json"),
        headers=dict(headers or {}),
    )


def _field_path(location: Sequence[Any]) -> str:
    """('body', 'lines', 0, 'quantity') becomes 'lines[0].quantity'."""
    parts = [part for part in location if part not in {"body", "query", "path", "header", "cookie"}]
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "request"


def validation_details(exc: RequestValidationError) -> list[ErrorDetail]:
    details = []
    for item in exc.errors():
        issue = str(item.get("msg", "is not valid"))
        details.append(ErrorDetail(field=_field_path(item.get("loc", ())), issue=issue))
    return details


def _expect[T: Exception](exc: Exception, kind: type[T]) -> T:
    """Narrow the `Exception` that Starlette hands to a handler registered for `kind`."""
    if not isinstance(exc, kind):
        raise TypeError(f"Handler for {kind.__name__} received {type(exc).__name__}")
    return exc


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    error = _expect(exc, AppError)
    return error_response(
        request, error.code, error.message, details=error.details, headers=error.headers
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    error = _expect(exc, RequestValidationError)
    return error_response(request, ErrorCode.VALIDATION_ERROR, details=validation_details(error))


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    error = _expect(exc, StarletteHTTPException)
    code = HTTP_STATUS_TO_CODE.get(error.status_code)
    if code is None:
        # Statuses without a code of their own (400, 413 and so on) keep their status.
        code = ErrorCode.VALIDATION_ERROR if error.status_code < 500 else ErrorCode.INTERNAL
    headers = dict(error.headers or {})
    return error_response(request, code, status_code=error.status_code, headers=headers)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "request.unhandled_error",
        request_id=request_id_of(request),
        path=request.url.path,
        exc_info=exc,
    )
    return error_response(request, ErrorCode.INTERNAL)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
