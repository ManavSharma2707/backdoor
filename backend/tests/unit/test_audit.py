"""Audit helpers: JSON safe payloads, redaction, diffs and address cleaning."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from app.core.audit import (
    AuditAction,
    changed_fields,
    clean_ip,
    email_fingerprint,
    json_safe,
)


def test_json_safe_keeps_money_as_strings_and_formats_dates_and_ids() -> None:
    ident = uuid.uuid4()
    payload = {
        "weekly_budget": Decimal("150000.50"),
        "on": date(2026, 10, 13),
        "at": datetime(2026, 10, 13, 6, 0, tzinfo=UTC),
        "id": ident,
        "nested": [{"qty": Decimal("1.500")}],
        "missing": None,
        "flag": True,
    }
    assert json_safe(payload) == {
        "weekly_budget": "150000.50",
        "on": "2026-10-13",
        "at": "2026-10-13T06:00:00+00:00",
        "id": str(ident),
        "nested": [{"qty": "1.500"}],
        "missing": None,
        "flag": True,
    }


def test_json_safe_redacts_secrets_at_any_depth() -> None:
    cleaned = json_safe(
        {
            "password": "hunter2hunter2",
            "new_password": "hunter3hunter3",
            "profile": {"refresh_token": "abc", "api_key": "k", "name": "Asha"},
            "authorization": "Bearer abc",
        }
    )
    assert cleaned["password"] == "[redacted]"
    assert cleaned["new_password"] == "[redacted]"
    assert cleaned["profile"] == {
        "refresh_token": "[redacted]",
        "api_key": "[redacted]",
        "name": "Asha",
    }
    assert cleaned["authorization"] == "[redacted]"


def test_json_safe_clips_long_text_and_converts_enums_and_sets() -> None:
    class Color(StrEnum):
        RED = "red"

    cleaned = json_safe({"note": "x" * 1000, "color": Color.RED, "ids": {3}})
    assert len(cleaned["note"]) == 300
    assert cleaned["color"] == "red"
    assert cleaned["ids"] == [3]


def test_changed_fields_returns_only_what_differs() -> None:
    before = {"a": 1, "b": 2, "c": 3}
    after = {"a": 1, "b": 5, "c": 3, "d": 9}
    assert changed_fields(before, after) == ({"b": 2, "d": None}, {"b": 5, "d": 9})
    assert changed_fields(before, dict(before)) == ({}, {})


def test_clean_ip_accepts_addresses_and_drops_everything_else() -> None:
    assert clean_ip("203.0.113.9") == "203.0.113.9"
    assert clean_ip("2001:db8::1") == "2001:db8::1"
    assert clean_ip("testclient") is None
    assert clean_ip("") is None
    assert clean_ip(None) is None


def test_email_fingerprint_is_stable_short_and_case_insensitive() -> None:
    assert email_fingerprint(" Owner@Example.com ") == email_fingerprint("owner@example.com")
    assert len(email_fingerprint("owner@example.com")) == 16
    assert "owner" not in email_fingerprint("owner@example.com")


def test_audit_actions_cover_the_events_in_the_security_spec() -> None:
    names = {action.value for action in AuditAction}
    required = {
        "auth.login.success",
        "auth.login.failure",
        "auth.lockout",
        "auth.logout",
        "auth.logout_all",
        "auth.refresh_reuse",
        "auth.password_change",
        "settings.update",
        "product.create",
        "product.update",
        "product.price_change",
        "product.deactivate",
        "supplier.update",
        "terms.update",
        "sale.create",
        "sale.void",
        "return.create",
        "po.create",
        "po.send",
        "po.cancel",
        "po.close",
        "receipt.post",
        "adjustment.create",
        "count.post",
        "batch.write_off",
    }
    assert required <= names
