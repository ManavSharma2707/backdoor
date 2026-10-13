"""Structured JSON logging with redaction of sensitive fields."""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

REDACTED = "[redacted]"
SENSITIVE_NAMES = frozenset(
    {"authorization", "cookie", "set_cookie", "password", "token", "secret", "api_key", "apikey"}
)
SENSITIVE_SUFFIXES = ("_password", "_token", "_secret", "_api_key", "_cookie", "_authorization")
SENSITIVE_PREFIXES = ("password",)


def is_sensitive_key(key: str) -> bool:
    name = key.lower().replace("-", "_")
    return (
        name in SENSITIVE_NAMES
        or name.endswith(SENSITIVE_SUFFIXES)
        or name.startswith(SENSITIVE_PREFIXES)
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if isinstance(key, str) and is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(item) for item in value)
    return value


def redact_processor(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> EventDict:
    """Replace the value of any sensitive key, at any depth."""
    return dict(_redact(event_dict))


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Route structlog and stdlib logging (uvicorn, sqlalchemy) through one pipeline."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_processor,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # The request middleware writes one structured line per request, so silence uvicorn's own.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_request_context(**values: Any) -> None:
    """Attach request_id, tenant_id, user_id, route to every log line of this request."""
    structlog.contextvars.bind_contextvars(**values)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
