"""Every failure uses the same envelope (api-spec.md section 1)."""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.messages import DEFAULT_MESSAGES, STATUS_BY_CODE, ErrorCode
from app.core.text import BANNED_WORDS, contains_long_dash
from app.schemas.common import ErrorDetail

# The table from api-spec.md, written out so a change to either side is noticed.
SPEC_STATUS = {
    "VALIDATION_ERROR": 422,
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "IDEMPOTENCY_MISMATCH": 422,
    "RATE_LIMITED": 429,
    "INSUFFICIENT_STOCK": 409,
    "BATCH_EXPIRED": 409,
    "RECEIPT_EXCEEDS_ORDER": 409,
    "RETURN_EXCEEDS_SOLD": 409,
    "PO_STATE_INVALID": 409,
    "REPORT_NOT_READY": 409,
    "MISSING_SUPPLIER_OR_COST": 409,
    "AGENTS_DISABLED": 503,
    "QUOTA_EXHAUSTED": 503,
    "INTERNAL": 500,
}


class Line(BaseModel):
    quantity: int = Field(gt=0)


class Basket(BaseModel):
    lines: list[Line]


@pytest.fixture
def routes(app: FastAPI) -> FastAPI:
    @app.get("/api/v1/_t/conflict")
    def conflict() -> None:
        raise AppError(
            ErrorCode.INSUFFICIENT_STOCK,
            "Only 4 packs of Biscuits 100 g are in stock.",
            details=[ErrorDetail(field="lines[0].quantity", issue="only 4 in stock")],
        )

    @app.get("/api/v1/_t/limited")
    def limited() -> None:
        raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"})

    @app.get("/api/v1/_t/teapot")
    def teapot() -> None:
        raise HTTPException(status_code=418, detail="I am a teapot")

    @app.get("/api/v1/_t/unauthorised")
    def unauthorised() -> None:
        raise HTTPException(status_code=401, detail="no", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/api/v1/_t/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail: password=hunter2")

    @app.post("/api/v1/_t/basket")
    def basket(body: Basket) -> dict[str, int]:
        return {"lines": len(body.lines)}

    @app.get("/api/v1/_t/search")
    def search(page: int = Query(ge=1)) -> dict[str, int]:
        return {"page": page}

    @app.get("/api/v1/_t/dashy")
    def dashy() -> None:
        raise AppError(ErrorCode.CONFLICT, "Stock is low \u2014 order today, it is simply easy!")

    return app


@pytest.fixture
def api(routes: FastAPI) -> TestClient:
    return TestClient(routes, raise_server_exceptions=False)


def assert_envelope(response: Any, code: str, status: int) -> dict[str, Any]:
    assert response.status_code == status
    body = response.json()
    assert list(body) == ["error"]
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error  # type: ignore[no-any-return]


def test_every_documented_code_has_the_documented_status() -> None:
    for code, status in SPEC_STATUS.items():
        assert STATUS_BY_CODE[ErrorCode(code)] == status, code


def test_every_code_has_a_default_message() -> None:
    assert set(DEFAULT_MESSAGES) == set(ErrorCode)


def test_default_messages_follow_the_copy_rules() -> None:
    for code, message in DEFAULT_MESSAGES.items():
        assert not contains_long_dash(message), code
        assert "!" not in message, code
        lowered = message.lower()
        assert not [w for w in BANNED_WORDS if f" {w.lower()} " in f" {lowered} "], code


def test_domain_error_uses_its_message_details_and_status(api: TestClient) -> None:
    error = assert_envelope(api.get("/api/v1/_t/conflict"), "INSUFFICIENT_STOCK", 409)
    assert error["message"] == "Only 4 packs of Biscuits 100 g are in stock."
    assert error["details"] == [{"field": "lines[0].quantity", "issue": "only 4 in stock"}]


def test_error_headers_are_passed_through(api: TestClient) -> None:
    response = api.get("/api/v1/_t/limited")
    assert_envelope(response, "RATE_LIMITED", 429)
    assert response.headers["Retry-After"] == "30"


def test_validation_errors_name_the_field(api: TestClient) -> None:
    response = api.post("/api/v1/_t/basket", json={"lines": [{"quantity": 2}, {"quantity": 0}]})
    error = assert_envelope(response, "VALIDATION_ERROR", 422)
    assert error["details"][0]["field"] == "lines[1].quantity"
    assert "greater than 0" in error["details"][0]["issue"]


def test_validation_errors_cover_query_parameters_and_missing_bodies(api: TestClient) -> None:
    error = assert_envelope(api.get("/api/v1/_t/search?page=0"), "VALIDATION_ERROR", 422)
    assert error["details"][0]["field"] == "page"
    error = assert_envelope(api.post("/api/v1/_t/basket"), "VALIDATION_ERROR", 422)
    assert error["details"]


def test_unknown_path_is_a_not_found_envelope(api: TestClient) -> None:
    assert_envelope(api.get("/api/v1/nothing-here"), "NOT_FOUND", 404)


def test_wrong_method_is_a_method_not_allowed_envelope(api: TestClient) -> None:
    assert_envelope(api.post("/api/v1/health"), "METHOD_NOT_ALLOWED", 405)


def test_http_exception_headers_survive(api: TestClient) -> None:
    response = api.get("/api/v1/_t/unauthorised")
    assert_envelope(response, "UNAUTHENTICATED", 401)
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_statuses_without_a_code_keep_their_status(api: TestClient) -> None:
    error = assert_envelope(api.get("/api/v1/_t/teapot"), "VALIDATION_ERROR", 418)
    assert "teapot" not in error["message"]


def test_unexpected_errors_never_leak_details(api: TestClient) -> None:
    response = api.get("/api/v1/_t/boom")
    error = assert_envelope(response, "INTERNAL", 500)
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    assert error["message"] == DEFAULT_MESSAGES[ErrorCode.INTERNAL]
    assert error["details"] == []


def test_messages_are_cleaned_before_they_are_sent(api: TestClient) -> None:
    error = assert_envelope(api.get("/api/v1/_t/dashy"), "CONFLICT", 409)
    assert error["message"] == "Stock is low, order today, it is easy."


def test_unexpected_errors_still_carry_request_id_and_security_headers(api: TestClient) -> None:
    response = api.get("/api/v1/_t/boom", headers={"Origin": "http://localhost:5173"})
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
