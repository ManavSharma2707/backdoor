from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.version import APP_VERSION


@pytest.mark.parametrize("path", ["/api/v1/health", "/health"])
def test_liveness(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": APP_VERSION}


@pytest.mark.parametrize("path", ["/api/v1/health/ready", "/health/ready"])
def test_readiness_reports_the_database(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": APP_VERSION,
        "database": "up",
        "migration": "current",
    }


def test_liveness_does_not_touch_the_database(app: FastAPI) -> None:
    def broken() -> Iterator[Session]:
        raise AssertionError("liveness must not open a session")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_readiness_is_503_when_the_database_is_down(app: FastAPI) -> None:
    class DeadSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def dead() -> Iterator[DeadSession]:
        yield DeadSession()

    app.dependency_overrides[get_session] = dead
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "version": APP_VERSION, "database": "down"}
    assert "connection refused" not in response.text


def test_health_needs_no_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/health", headers={}).status_code == 200


def test_openapi_documents_the_versioned_paths_only(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    assert schema["info"]["title"] == "Backroom API"
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/health/ready" in schema["paths"]
    assert "/health" not in schema["paths"]
    assert "ErrorEnvelope" in schema["components"]["schemas"]


def test_docs_page_is_served(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 200


def test_readiness_is_503_when_migrations_are_behind(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.health.head_revision", lambda: "9999")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["migration"] == "behind"
    assert response.json()["database"] == "up"


def test_readiness_is_503_when_the_migration_table_is_missing(
    client: TestClient, db: Session
) -> None:
    db.execute(text("ALTER TABLE alembic_version RENAME TO alembic_version_gone"))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["migration"] == "unknown"
