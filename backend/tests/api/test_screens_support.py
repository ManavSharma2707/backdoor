"""Endpoints added for the first screens: sign in config, calendar, activity, bills by product."""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.reference import CalendarEvent
from tests import factories
from tests.api.helpers import API, line, post_sale, sale_payload, stock_up
from tests.conftest import TwoTenants


@pytest.fixture
def demo_client(app: FastAPI, test_settings: Settings) -> Iterator[TestClient]:
    flagged = create_app(test_settings.model_copy(update={"demo_login_enabled": True}))
    flagged.dependency_overrides.update(app.dependency_overrides)
    with TestClient(flagged, raise_server_exceptions=False) as client:
        yield client


def test_auth_config_is_public_and_empty_when_demo_login_is_off(client: TestClient) -> None:
    response = client.get(f"{API}/auth/config")
    assert response.status_code == 200
    assert response.json() == {"demo_login_enabled": False, "demo_profiles": []}


def test_auth_config_lists_only_active_synthetic_businesses_when_on(
    demo_client: TestClient, db: Session
) -> None:
    shown = factories.make_tenant(db, profile_key="shown_one", name="Shown Stores")
    factories.make_tenant(db, profile_key="real_one", name="Real Stores", is_synthetic=False)
    factories.make_tenant(db, profile_key="off_one", name="Closed Stores", is_active=False)
    factories.make_tenant(db, profile_key=None, name="No Key Stores")
    db.commit()
    body = demo_client.get(f"{API}/auth/config").json()
    assert body["demo_login_enabled"] is True
    assert {"key": "shown_one", "name": shown.name} in body["demo_profiles"]
    keys = {profile["key"] for profile in body["demo_profiles"]}
    assert keys.isdisjoint({"real_one", "off_one"})
    assert all(set(profile) == {"key", "name"} for profile in body["demo_profiles"])


def test_calendar_events_need_a_token(client: TestClient) -> None:
    assert client.get(f"{API}/calendar/events").status_code == 401


def test_calendar_events_filter_by_dates_and_kind(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    for slug, name, kind, start, end, active in [
        ("t-a", "Test Fest", "festival", date(2031, 3, 10), date(2031, 3, 12), True),
        ("t-b", "Test Season", "season", date(2031, 6, 1), date(2031, 8, 31), True),
        ("t-c", "Test Hidden", "festival", date(2031, 3, 11), date(2031, 3, 11), False),
    ]:
        db.add(
            CalendarEvent(
                slug=slug,
                event_key=slug,
                name=name,
                kind=kind,
                start_date=start,
                end_date=end,
                is_active=active,
            )
        )
    db.commit()
    headers = two_tenants.a.headers
    march = client.get(
        f"{API}/calendar/events", headers=headers, params={"from": "2031-03-01", "to": "2031-03-31"}
    ).json()
    assert [event["name"] for event in march] == ["Test Fest"]
    assert march[0]["is_verified"] is False
    seasons = client.get(
        f"{API}/calendar/events",
        headers=headers,
        params={"from": "2031-01-01", "to": "2031-12-31", "kind": "season"},
    ).json()
    assert [event["name"] for event in seasons] == ["Test Season"]


def test_activity_needs_a_token_and_starts_empty(
    client: TestClient, two_tenants: TwoTenants
) -> None:
    assert client.get(f"{API}/dashboard/activity").status_code == 401
    body = client.get(f"{API}/dashboard/activity", headers=two_tenants.a.headers).json()
    assert body == {"items": []}


def test_activity_shows_own_records_newest_first_and_never_the_other_tenants(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    stock_up(db, a.tenant, a.user, a.product, "10")
    stock_up(db, b.tenant, b.user, b.product, "10")
    db.commit()
    first = post_sale(client, a.headers, sale_payload(line(a.product, "1")))
    assert first.status_code == 201
    other = post_sale(client, b.headers, sale_payload(line(b.product, "1")))
    assert other.status_code == 201
    voided = client.post(
        f"{API}/sales/{first.json()['id']}/void", headers=a.headers, json={"reason": "Test"}
    )
    assert voided.status_code == 200

    items = client.get(f"{API}/dashboard/activity", headers=a.headers).json()["items"]
    assert [item["kind"] for item in items] == ["bill_voided"]
    assert items[0]["ref"] == first.json()["bill_no"]
    assert [item["entity_id"] for item in items] == [first.json()["id"]]
    assert client.get(f"{API}/dashboard/activity?limit=0", headers=a.headers).status_code == 422


def test_bills_can_be_listed_by_product_without_leaking_the_other_tenant(
    client: TestClient, db: Session, two_tenants: TwoTenants
) -> None:
    a, b = two_tenants.a, two_tenants.b
    spare = factories.make_product(db, a.tenant, category=a.category)
    for bundle in (a, b):
        stock_up(db, bundle.tenant, bundle.user, bundle.product, "10")
    stock_up(db, a.tenant, a.user, spare, "10")
    db.commit()
    with_product = post_sale(client, a.headers, sale_payload(line(a.product, "1"))).json()
    post_sale(client, a.headers, sale_payload(line(spare, "1")))
    post_sale(client, b.headers, sale_payload(line(b.product, "1")))

    mine = client.get(f"{API}/sales", headers=a.headers, params={"product_id": str(a.product.id)})
    assert [bill["id"] for bill in mine.json()["items"]] == [with_product["id"]]
    crossed = client.get(
        f"{API}/sales", headers=b.headers, params={"product_id": str(a.product.id)}
    )
    assert crossed.json()["items"] == []
