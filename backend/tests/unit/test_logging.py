import json
import logging

import pytest

from app.core.logging import (
    REDACTED,
    bind_request_context,
    clear_request_context,
    configure_logging,
    get_logger,
    is_sensitive_key,
    redact_processor,
)


@pytest.mark.parametrize(
    "key",
    [
        "authorization",
        "Authorization",
        "cookie",
        "Set-Cookie",
        "password",
        "new_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "gemini_api_key",
        "x-api-key",
        "jwt_secret",
        "secret",
    ],
)
def test_sensitive_keys_are_detected(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key", ["request_id", "tenant_id", "tokens_in", "token_count", "path", "status", "duration_ms"]
)
def test_ordinary_keys_are_not_redacted(key: str) -> None:
    assert not is_sensitive_key(key)


def test_redaction_is_recursive() -> None:
    event = {
        "event": "login",
        "headers": {"Authorization": "Bearer abc", "accept": "json"},
        "items": [{"refresh_token": "r1"}, {"ok": 1}],
        "password": "hunter2",
    }
    result = redact_processor(None, "info", event)
    assert result["password"] == REDACTED
    assert result["headers"] == {"Authorization": REDACTED, "accept": "json"}
    assert result["items"] == [{"refresh_token": REDACTED}, {"ok": 1}]
    assert event["password"] == "hunter2"  # the input is not mutated


def test_output_is_json_with_context_and_redaction(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    try:
        bind_request_context(request_id="req-12345678")
        get_logger("test").info("something.happened", tenant_id="t1", api_key="abc123")
        logging.getLogger("stdlib.logger").warning("from stdlib")
    finally:
        clear_request_context()
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    structured, stdlib = lines[0], lines[1]
    assert structured["event"] == "something.happened"
    assert structured["request_id"] == "req-12345678"
    assert structured["api_key"] == REDACTED
    assert structured["level"] == "info"
    assert "timestamp" in structured
    assert stdlib["event"] == "from stdlib"
