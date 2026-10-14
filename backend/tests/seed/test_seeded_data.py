"""The seeded database: validators, ledger rules, owner logins, determinism and text rules."""

import re
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import PasswordService
from app.engine.ledger_rules import check_movement
from app.main import create_app
from seed import checksum as checksum_module
from seed.corpus.generator import app_docs, build_corpus
from seed.generate import checksum, generate_tenant
from seed.model import tenant_uuid
from seed.profiles import DEFAULT_BASE_SEED, PROFILES
from seed.size_report import collect
from seed.validate import run_checks
from tests.seed.conftest import END, SCALE, SEED_PASSWORD, Seeded
from tests.seed.test_catalog import LOCATION_WORDS


@pytest.mark.parametrize("key", list(PROFILES))
def test_validators_pass_for_every_tenant(seeded: Seeded, key: str) -> None:
    with seeded.session() as session:
        failed = [c for c in run_checks(session, PROFILES[key], seeded.generated[key]) if not c.ok]
    assert not failed, [(c.name, c.detail) for c in failed]


@pytest.mark.parametrize("key", list(PROFILES))
def test_every_movement_follows_the_sign_rules(seeded: Seeded, key: str) -> None:
    with seeded.session() as session:
        rows = session.execute(
            text(
                "SELECT movement_type, quantity_delta FROM inventory_movements WHERE tenant_id=:t"
            ),
            {"t": tenant_uuid(PROFILES[key])},
        ).all()
    assert rows
    for movement_type, delta in rows:
        check_movement(movement_type, Decimal(delta))


@pytest.mark.parametrize("key", list(PROFILES))
def test_sales_are_consistent_with_the_ledger(seeded: Seeded, key: str) -> None:
    with seeded.session() as session:
        tid = tenant_uuid(PROFILES[key])
        sold_lines = session.execute(
            text(
                "SELECT COALESCE(SUM(l.quantity),0) FROM sale_lines l JOIN sales s ON s.tenant_id=l.tenant_id AND s.id=l.sale_id "
                "WHERE l.tenant_id=:t AND s.status='completed'"
            ),
            {"t": tid},
        ).scalar_one()
        moved = session.execute(
            text(
                "SELECT COALESCE(SUM(-quantity_delta),0) FROM inventory_movements WHERE tenant_id=:t AND movement_type='sale'"
            ),
            {"t": tid},
        ).scalar_one()
        reversed_ = session.execute(
            text(
                "SELECT COALESCE(SUM(quantity_delta),0) FROM inventory_movements WHERE tenant_id=:t AND movement_type='void_reversal'"
            ),
            {"t": tid},
        ).scalar_one()
        sources = (
            session.execute(
                text("SELECT DISTINCT source FROM sales WHERE tenant_id=:t"), {"t": tid}
            )
            .scalars()
            .all()
        )
    assert sold_lines == moved - reversed_
    assert sources == ["seed"]


def test_history_window_and_bill_numbers(seeded: Seeded) -> None:
    with seeded.session() as session:
        low, high = session.execute(
            text("SELECT MIN(business_date), MAX(business_date) FROM sales WHERE tenant_id=:t"),
            {"t": tenant_uuid(PROFILES["fmcg_a"])},
        ).one()
        opening = (
            session.execute(
                text(
                    "SELECT DISTINCT business_date FROM inventory_movements WHERE tenant_id=:t AND movement_type='opening'"
                ),
                {"t": tenant_uuid(PROFILES["fmcg_a"])},
            )
            .scalars()
            .all()
        )
        bills = (
            session.execute(
                text("SELECT bill_no FROM sales WHERE tenant_id=:t LIMIT 500"),
                {"t": tenant_uuid(PROFILES["fmcg_a"])},
            )
            .scalars()
            .all()
        )
    assert str(low) == "2025-04-14"
    assert str(high) == "2026-10-11"
    assert [str(d) for d in opening] == ["2025-04-13"]
    assert all(re.fullmatch(r"B\d{4}-\d{5}", b) for b in bills)


@pytest.mark.parametrize("key", list(PROFILES))
def test_owner_can_sign_in_with_the_seed_password(seeded: Seeded, key: str) -> None:
    profile = PROFILES[key]
    application = create_app(seeded.settings)

    def override() -> Iterator[Session]:
        with Session(seeded.engine) as session:
            yield session

    application.dependency_overrides[get_session] = override
    with TestClient(application) as client:
        ok = client.post(
            "/api/v1/auth/login", json={"email": profile.owner_email, "password": SEED_PASSWORD}
        )
        assert ok.status_code == 200, ok.text
        token = ok.json()["access_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["tenant"]["name"] == profile.name
        bad = client.post(
            "/api/v1/auth/login",
            json={"email": profile.owner_email, "password": "not-the-password-0000"},
        )
        assert bad.status_code == 401


def test_password_hashes_are_argon2id_and_not_the_password(seeded: Seeded) -> None:
    with seeded.session() as session:
        hashes = session.execute(text("SELECT password_hash FROM users")).scalars().all()
    assert len(hashes) == 4
    service = PasswordService(seeded.settings)
    for h in hashes:
        assert h.startswith("$argon2id$")
        assert SEED_PASSWORD not in h
        assert service.verify(h, SEED_PASSWORD)


def test_each_tenant_is_synthetic_and_isolated(seeded: Seeded) -> None:
    with seeded.session() as session:
        flags = session.execute(text("SELECT is_synthetic FROM tenants")).scalars().all()
        stray = session.execute(
            text(
                "SELECT COUNT(*) FROM sale_lines l JOIN products p ON p.id = l.product_id AND p.tenant_id <> l.tenant_id"
            )
        ).scalar_one()
    assert flags == [True] * 4
    assert stray == 0


def test_same_seed_gives_the_same_checksum() -> None:
    a = checksum(generate_tenant(PROFILES["fmcg_a"], DEFAULT_BASE_SEED, END, SCALE))
    b = checksum(generate_tenant(PROFILES["fmcg_a"], DEFAULT_BASE_SEED, END, SCALE))
    c = checksum(generate_tenant(PROFILES["fmcg_a"], DEFAULT_BASE_SEED + 1, END, SCALE))
    assert a == b
    assert a != c


def test_checksum_command_reports_identical_runs(capsys: pytest.CaptureFixture[str]) -> None:
    code = checksum_module.main(["--tenants", "med_a", "--scale", str(SCALE), "--twice"])
    assert code == 0
    assert "identical" in capsys.readouterr().out


def test_other_streams_do_not_shift_when_one_purpose_changes() -> None:
    from seed.rng import stream

    first = stream(DEFAULT_BASE_SEED, 0, "demand").random(5).tolist()
    stream(DEFAULT_BASE_SEED, 0, "bills").random(100)
    again = stream(DEFAULT_BASE_SEED, 0, "demand").random(5).tolist()
    assert first == again
    assert first != stream(DEFAULT_BASE_SEED, 1, "demand").random(5).tolist()


def test_size_report_is_small_at_this_scale(seeded: Seeded) -> None:
    with seeded.session() as session:
        total = sum(t + i for _, _, t, i in collect(session))
    assert total < 250.0


# ---------------------------------------------------------------- text rules

DASHES = ("—", "–")


def _all_seed_text(seeded: Seeded) -> list[str]:
    values: list[str] = []
    with seeded.session() as session:
        for sql in (
            "SELECT name FROM tenants",
            "SELECT name || ' ' || COALESCE(contact_name, '') FROM suppliers",
            "SELECT name || ' ' || COALESCE(brand, '') || ' ' || COALESCE(pack_label, '') FROM products",
            "SELECT name FROM categories",
            "SELECT name FROM promotions",
            "SELECT COALESCE(note, '') FROM inventory_movements WHERE note IS NOT NULL GROUP BY note",
            "SELECT COALESCE(reason, '') FROM sale_returns GROUP BY reason",
            "SELECT COALESCE(exception_note, '') FROM goods_receipts WHERE exception_note IS NOT NULL GROUP BY exception_note",
            "SELECT COALESCE(cancel_reason, '') FROM purchase_orders WHERE cancel_reason IS NOT NULL GROUP BY cancel_reason",
            "SELECT content FROM knowledge_chunks",
            "SELECT title FROM knowledge_documents",
            "SELECT COALESCE(source_note, '') FROM calendar_events",
            "SELECT full_name || ' ' || email FROM users",
        ):
            values += [str(v) for v in session.execute(text(sql)).scalars().all()]
    return values


def test_no_long_dashes_in_any_seeded_text(seeded: Seeded) -> None:
    for value in _all_seed_text(seeded):
        assert not any(d in value for d in DASHES), value[:80]


def test_no_locations_in_any_seeded_text(seeded: Seeded) -> None:
    blocked = [
        w
        for w in LOCATION_WORDS
        if w not in {"india", "road", "street", "colony", "nagar", "district"}
    ]
    for value in _all_seed_text(seeded):
        low = value.lower()
        for word in blocked:
            assert not re.search(rf"\b{word}\b", low), (word, value[:80])


def test_corpus_text_follows_the_copy_rules() -> None:
    from app.core.text import BANNED_WORDS

    docs = list(app_docs())
    for key, profile in PROFILES.items():
        from seed.model import load_catalog

        docs += build_corpus(load_catalog(profile), DEFAULT_BASE_SEED)
        del key
    assert len(docs) > 60
    for doc in docs:
        body = f"{doc.title}. {doc.text}"
        assert not any(d in body for d in DASHES)
        assert "!" not in body
        assert ";" not in body
        for word in BANNED_WORDS:
            assert not re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", body, re.IGNORECASE), (
                word,
                body[:60],
            )


def test_supplier_documents_match_the_supplier_table(seeded: Seeded) -> None:
    with seeded.session() as session:
        suppliers = session.execute(
            text(
                "SELECT s.code, s.name, s.return_window_days, s.accepts_expiry_returns, s.expiry_return_window_days, "
                "s.min_order_value, s.payment_terms_days FROM suppliers s WHERE s.tenant_id=:t AND s.default_lead_time_days IS NOT NULL"
            ),
            {"t": tenant_uuid(PROFILES["med_b"])},
        ).all()
        docs = {
            (r[0], r[1]): r[2]
            for r in session.execute(
                text(
                    "SELECT d.metadata->>'supplier_code', d.metadata->>'topic', string_agg(c.content, ' ') "
                    "FROM knowledge_documents d JOIN knowledge_chunks c ON c.document_id=d.id "
                    "WHERE d.tenant_id=:t AND d.doc_type='supplier_policy' GROUP BY 1,2"
                ),
                {"t": tenant_uuid(PROFILES["med_b"])},
            )
        }
    assert suppliers
    for code, _name, window, accepts, expiry_window, mov, pay in suppliers:
        terms = docs[(code, "terms")]
        assert f"{window} day" in terms
        if accepts:
            assert str(expiry_window) in terms
        else:
            assert "not" in terms.lower() or "no return" in terms.lower()
        delivery = docs[(code, "delivery")]
        assert f"{int(mov):,}" in delivery
        if pay:
            assert f"{pay} day" in terms
        else:
            assert "on delivery" in terms


def test_knowledge_is_stored_without_embeddings(seeded: Seeded) -> None:
    with seeded.session() as session:
        embedded = session.execute(
            text("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL")
        ).scalar_one()
        global_chunks = session.execute(
            text("SELECT COUNT(*) FROM knowledge_chunks WHERE tenant_id IS NULL")
        ).scalar_one()
        per_tenant = session.execute(
            text(
                "SELECT tenant_id, COUNT(*) FROM knowledge_documents WHERE tenant_id IS NOT NULL GROUP BY 1"
            )
        ).all()
    assert embedded == 0
    assert 20 <= global_chunks <= 60
    assert len(per_tenant) == 4
    assert all(n >= 15 for _, n in per_tenant)


@pytest.mark.parametrize(
    "table",
    ["sale_lines", "sale_return_lines", "inventory_movements", "forecast_values", "agent_steps"],
)
def test_identity_sequences_are_past_the_loaded_ids(seeded: Seeded, table: str) -> None:
    """Regression: COPY with explicit ids left the sequences at 1, so the first new bill failed."""
    with seeded.session() as session:
        largest = session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar_one()
        issued = session.execute(
            text("SELECT nextval(pg_get_serial_sequence(:table, 'id'))"), {"table": table}
        ).scalar_one()
    assert issued > largest
