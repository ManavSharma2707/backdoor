import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import configure_logging
from app.main import create_app

ORIGIN = "http://localhost:5173"
PRODUCTION = {
    "app_env": "production",
    "database_url": "postgresql+psycopg://u:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
    "jwt_secret": "x" * 48,
    "job_token": "y" * 48,
    "cookie_secure": True,
    "cors_origins": "https://backroom.vercel.app",
}


def test_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_a_valid_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-12345"})
    assert response.headers["X-Request-ID"] == "trace-abc-12345"


@pytest.mark.parametrize(
    "bad", ["short", "has spaces in it!!", "x" * 200, "<script>alert(1)</script>"]
)
def test_an_unsafe_request_id_is_replaced(client: TestClient, bad: str) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": bad})
    assert response.headers["X-Request-ID"] != bad
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_each_request_gets_its_own_id(client: TestClient) -> None:
    ids = {client.get("/api/v1/health").headers["X-Request-ID"] for _ in range(5)}
    assert len(ids) == 5


def test_security_headers(client: TestClient) -> None:
    headers = client.get("/api/v1/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"


def test_security_headers_are_on_error_responses_too(client: TestClient) -> None:
    headers = client.get("/api/v1/no-such-route").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Request-ID" in headers


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/reports/latest", "/api/v1/exports/x"])
def test_session_and_report_responses_are_not_cacheable(client: TestClient, path: str) -> None:
    assert client.get(path).headers["Cache-Control"] == "no-store"


def test_health_may_be_cached_by_default(client: TestClient) -> None:
    assert "Cache-Control" not in client.get("/api/v1/health").headers


def test_hsts_is_off_locally_and_on_elsewhere() -> None:
    local = create_app(Settings(app_env="local", _env_file=None))  # type: ignore[call-arg]
    production = create_app(Settings(**PRODUCTION, _env_file=None))  # type: ignore[arg-type]
    assert "Strict-Transport-Security" not in TestClient(local).get("/health").headers
    hsts = TestClient(production).get("/health").headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts


def test_cors_allows_the_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_cors_exposes_the_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


def test_cors_ignores_other_origins(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers
    assert response.status_code == 200


def test_cors_preflight_from_other_origins_is_refused(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_one_structured_access_line_per_request(
    app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", json_output=True)
    with TestClient(app) as client:
        capsys.readouterr()
        response = client.get("/api/v1/health", headers={"Authorization": "Bearer secret-token"})
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    access = [line for line in lines if line.get("event") == "request.completed"]
    assert len(access) == 1
    line = access[0]
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert line["status"] == 200
    assert line["method"] == "GET"
    assert line["route"] == "/api/v1/health"
    assert line["duration_ms"] >= 0
    assert "secret-token" not in json.dumps(line)


def test_access_log_names_the_route_template_with_its_prefix(
    app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    @app.get("/api/v1/_t/items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    configure_logging("INFO", json_output=True)
    with TestClient(app) as client:
        capsys.readouterr()
        client.get("/api/v1/_t/items/42")
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    access = next(line for line in lines if line.get("event") == "request.completed")
    assert access["path"] == "/api/v1/_t/items/42"
    assert access["route"] == "/api/v1/_t/items/{item_id}"
