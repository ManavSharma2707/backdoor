"""Fixtures for HTTP level tests."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app


@pytest.fixture
def app(test_settings: Settings, db: Session) -> FastAPI:
    application = create_app(test_settings)

    def override_session() -> Iterator[Session]:
        yield db

    application.dependency_overrides[get_session] = override_session
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Unhandled errors must come back as the 500 envelope, not be re-raised into the test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
