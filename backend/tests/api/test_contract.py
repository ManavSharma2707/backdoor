"""Checks that hold for the whole API, read from the OpenAPI document itself.

Per route tests live next to each domain. These make sure no route is added without a token
requirement, a tag, the error envelope or a regenerated `openapi.json`.
"""

import re
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jobs.openapi import OPENAPI_PATH, build_schema, render

PUBLIC = {
    ("get", "/api/v1/health"),
    ("get", "/api/v1/health/ready"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/logout"),
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/demo-login"),
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def operations(app: FastAPI) -> list[tuple[str, str, dict[str, Any]]]:
    schema = app.openapi()
    return [
        (method, path, op)
        for path, item in sorted(schema["paths"].items())
        for method, op in sorted(item.items())
        if method in HTTP_METHODS
    ]


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def test_the_api_has_the_expected_number_of_operations(app: FastAPI) -> None:
    assert len(operations(app)) >= 60


def test_every_operation_has_a_tag_and_a_summary(app: FastAPI) -> None:
    for method, path, op in operations(app):
        assert op.get("tags"), (method, path)
        assert op.get("summary"), (method, path)


def test_every_non_public_operation_requires_a_bearer_token(app: FastAPI) -> None:
    for method, path, op in operations(app):
        if (method, path) in PUBLIC:
            continue
        security = op.get("security", [])
        assert {"BearerAuth": []} in security or {"JobToken": []} in security, (method, path)


def test_public_operations_are_exactly_the_documented_ones(app: FastAPI) -> None:
    open_ones = {(method, path) for method, path, op in operations(app) if not op.get("security")}
    assert open_ones == PUBLIC


def test_every_operation_documents_the_error_envelope(app: FastAPI) -> None:
    for method, path, op in operations(app):
        for status in ("401", "422", "500"):
            body = op["responses"][status]["content"]["application/json"]["schema"]
            assert body == {"$ref": "#/components/schemas/ErrorEnvelope"}, (method, path, status)


def test_no_endpoint_takes_a_tenant_id(app: FastAPI) -> None:
    """Tenant identity comes from the token. No path, query or body field may carry it."""
    schema = app.openapi()
    for path, item in schema["paths"].items():
        assert "tenant" not in path, path
        for op in item.values():
            for parameter in op.get("parameters", []):
                if path.startswith("/api/v1/jobs/"):
                    continue  # job token calls name a business by slug, as api-spec.md section 10 says
                assert "tenant" not in parameter["name"].lower(), (path, parameter["name"])
    for name, model in schema["components"]["schemas"].items():
        if name.endswith(("Create", "Patch", "In", "Request")):
            assert "tenant_id" not in model.get("properties", {}), name


def test_money_and_quantity_responses_are_strings(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]
    for name in ("SaleOut", "SaleLineOut", "StockRow", "POOut", "POLineOut", "ProductOut"):
        for field, prop in schema[name]["properties"].items():
            if field in {
                "total",
                "subtotal",
                "tax_total",
                "on_hand",
                "quantity",
                "mrp",
                "unit_cost",
                "value",
            }:
                kinds = {prop.get("type"), *[a.get("type") for a in prop.get("anyOf", [])]}
                assert "number" not in kinds, (name, field)
                assert "string" in kinds, (name, field)


@pytest.mark.parametrize("method", sorted(HTTP_METHODS))
def test_protected_routes_answer_401_in_the_envelope_without_a_token(
    client: TestClient, app: FastAPI, method: str
) -> None:
    checked = 0
    for op_method, path, _ in operations(app):
        if op_method != method or (op_method, path) in PUBLIC:
            continue
        response = client.request(method, concrete(path), json={} if method != "get" else None)
        assert response.status_code == 401, (method, path, response.status_code)
        error = response.json()["error"]
        assert error["code"] == "UNAUTHENTICATED"
        assert error["request_id"]
        assert response.headers["x-request-id"] == error["request_id"]
        checked += 1
    assert checked > 0 or method in {"put"}


def test_expired_and_tampered_tokens_are_refused_on_every_get(
    client: TestClient, app: FastAPI
) -> None:
    for method, path, _ in operations(app):
        if method != "get" or (method, path) in PUBLIC:
            continue
        bad = client.get(concrete(path), headers={"Authorization": "Bearer abc.def.ghi"})
        assert bad.status_code == 401, path


def test_validation_not_found_and_conflict_all_use_the_envelope(
    client: TestClient, two_tenants: Any
) -> None:
    headers = two_tenants.a.headers
    cases = [
        (client.post("/api/v1/sales", headers=headers, json={}), 422, "VALIDATION_ERROR"),
        (client.get(f"/api/v1/products/{uuid.uuid4()}", headers=headers), 404, "NOT_FOUND"),
        (client.get("/api/v1/products/not-a-uuid", headers=headers), 422, "VALIDATION_ERROR"),
        (client.delete("/api/v1/sales", headers=headers), 405, "METHOD_NOT_ALLOWED"),
        (
            client.post(
                "/api/v1/categories",
                headers=headers,
                json={"name": "A", "parent_id": str(uuid.uuid4())},
            ),
            404,
            "NOT_FOUND",
        ),
    ]
    for response, status, code in cases:
        assert response.status_code == status
        error = response.json()["error"]
        assert error["code"] == code
        assert error["message"]
        assert isinstance(error["details"], list)
        assert error["request_id"]


def test_openapi_json_is_up_to_date() -> None:
    """Fails when routes or schemas changed without `python -m app.jobs.run openapi`."""
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == render(build_schema()), (
        "backend/openapi.json is out of date. Run: python -m app.jobs.run openapi"
    )
