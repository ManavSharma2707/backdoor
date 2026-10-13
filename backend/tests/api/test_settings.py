"""Business settings endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ops import AuditLog
from app.models.tenancy import BusinessSettings
from tests.conftest import TwoTenants

URL = "/api/v1/settings"


def test_every_settings_route_needs_a_token(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.patch(URL, json={}).status_code == 401


def test_get_returns_defaults_and_creates_the_row_once(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    assert db.get(BusinessSettings, a.tenant.id) is None
    body = client.get(URL, headers=a.headers).json()
    assert body["weekly_budget"] is None
    assert body["service_level"] == "0.950"
    assert body["review_period_days"] == 7
    assert body["default_lead_time_days"] == 3
    assert body["near_expiry_days"] == 90
    assert body["sellable_shelf_life_fraction"] == "0.60"
    assert body["pack_rounding"] == "up"
    assert body["censor_policy"] == "exclude"
    assert body["priority_weights"] == {
        "risk": 0.45,
        "value": 0.3,
        "confidence": 0.15,
        "excess": 0.1,
    }
    assert client.get(URL, headers=a.headers).json() == body


def test_patch_changes_only_the_fields_sent(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    response = client.patch(
        URL,
        headers=headers,
        json={
            "weekly_budget": "150000.00",
            "service_level": "0.97",
            "pack_rounding": "nearest_safe",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["weekly_budget"] == "150000.00"
    assert body["service_level"] == "0.970"
    assert body["pack_rounding"] == "nearest_safe"
    assert body["review_period_days"] == 7  # untouched
    assert client.get(URL, headers=headers).json() == body


def test_null_budget_clears_the_limit_but_other_fields_cannot_be_null(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    headers = two_tenants.a.headers
    client.patch(URL, headers=headers, json={"weekly_budget": "5000.00"})
    cleared = client.patch(URL, headers=headers, json={"weekly_budget": None})
    assert cleared.status_code == 200
    assert cleared.json()["weekly_budget"] is None
    refused = client.patch(URL, headers=headers, json={"service_level": None})
    assert refused.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_level", "0.40"),
        ("service_level", "1.0"),
        ("review_period_days", 0),
        ("review_period_days", 29),
        ("default_lead_time_days", -1),
        ("near_expiry_days", 3),
        ("nonmoving_days", 400),
        ("sellable_shelf_life_fraction", "0.05"),
        ("sellable_shelf_life_fraction", "1.5"),
        ("weekly_budget", "-1.00"),
        ("weekly_budget", "10.001"),
        ("weekly_budget", 100.5),
        ("pack_rounding", "down"),
        ("censor_policy", "impute"),
        ("backtest_origins", 2),
        ("forecast_horizon_days", 90),
        ("unknown_field", 1),
    ],
)
def test_out_of_range_values_are_rejected(
    client: TestClient, two_tenants: TwoTenants, field: str, value: object
) -> None:
    response = client.patch(URL, headers=two_tenants.a.headers, json={field: value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_priority_weights_must_add_up_to_one(client: TestClient, two_tenants: TwoTenants) -> None:
    headers = two_tenants.a.headers
    bad = client.patch(
        URL,
        headers=headers,
        json={"priority_weights": {"risk": 0.5, "value": 0.5, "confidence": 0.5, "excess": 0.5}},
    )
    assert bad.status_code == 422
    partial = client.patch(URL, headers=headers, json={"priority_weights": {"risk": 1.0}})
    assert partial.status_code == 422
    good = client.patch(
        URL,
        headers=headers,
        json={"priority_weights": {"risk": 0.4, "value": 0.3, "confidence": 0.2, "excess": 0.1}},
    )
    assert good.status_code == 200
    assert good.json()["priority_weights"]["risk"] == 0.4


def test_each_change_is_audited_with_a_small_diff(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a = two_tenants.a
    client.patch(URL, headers=a.headers, json={"weekly_budget": "1000.00", "review_period_days": 7})
    client.patch(URL, headers=a.headers, json={"weekly_budget": "2000.00"})
    client.patch(URL, headers=a.headers, json={"weekly_budget": "2000.00"})  # no change, no row
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == a.tenant.id, AuditLog.action == "settings.update")
            .order_by(AuditLog.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].before == {"weekly_budget": None}
    assert rows[0].after == {"weekly_budget": "1000.00"}
    assert rows[1].before == {"weekly_budget": "1000.00"}
    assert rows[1].after == {"weekly_budget": "2000.00"}
    assert rows[0].user_id == a.user.id


def test_settings_are_per_tenant(client: TestClient, two_tenants: TwoTenants) -> None:
    client.patch(URL, headers=two_tenants.a.headers, json={"weekly_budget": "9999.00"})
    other = client.get(URL, headers=two_tenants.b.headers).json()
    assert other["weekly_budget"] is None
