"""Engine settings, session helpers and the migrate command line."""

from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core import db as db_module
from app.core.config import Settings, get_settings
from app.jobs import run as run_module
from tests.conftest import scratch_database


@pytest.fixture
def point_settings_at(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Aim the cached settings, engine and session factory at another database."""

    def aim(url: str) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        db_module.dispose_engine()

    yield aim
    get_settings.cache_clear()
    db_module.dispose_engine()


@pytest.fixture
def captured_engines(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the arguments make_engine passes to create_engine instead of connecting."""
    calls: list[dict[str, Any]] = []

    def fake_create_engine(url: str, **kwargs: Any) -> None:
        calls.append({"url": url, **kwargs})

    monkeypatch.setattr(db_module, "create_engine", fake_create_engine)
    return calls


def test_engine_uses_the_pool_settings_from_the_spec(
    captured_engines: list[dict[str, Any]],
) -> None:
    db_module.make_engine(Settings(_env_file=None))  # type: ignore[call-arg]
    call = captured_engines[0]
    assert call["pool_size"] == 5
    assert call["max_overflow"] == 2
    assert call["pool_pre_ping"] is True
    assert call["pool_recycle"] == 1800


def test_pool_size_follows_the_environment_setting(captured_engines: list[dict[str, Any]]) -> None:
    settings = Settings(database_pool_size=3, database_max_overflow=1, _env_file=None)  # type: ignore[call-arg]
    db_module.make_engine(settings)
    assert (captured_engines[0]["pool_size"], captured_engines[0]["max_overflow"]) == (3, 1)


def test_transaction_pooler_turns_prepared_statements_off(
    captured_engines: list[dict[str, Any]],
) -> None:
    db_module.make_engine(Settings(_env_file=None))  # type: ignore[call-arg]
    db_module.make_engine(Settings(database_transaction_pooler=True, _env_file=None))  # type: ignore[call-arg]
    session_pooler, transaction_pooler = captured_engines
    assert session_pooler["connect_args"] == {}
    assert transaction_pooler["connect_args"] == {"prepare_threshold": None}


def test_session_scope_commits_on_success_and_rolls_back_on_error(
    test_database_url: str,
    engine: Engine,
    point_settings_at,  # type: ignore[no-untyped-def]
) -> None:
    point_settings_at(test_database_url)

    def fail_after_insert() -> None:
        with db_module.session_scope() as session:
            session.execute(text("INSERT INTO scope_probe VALUES (2)"))
            raise RuntimeError("boom")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE scope_probe (n int)"))
    try:
        with db_module.session_scope() as session:
            session.execute(text("INSERT INTO scope_probe VALUES (1)"))
        with pytest.raises(RuntimeError, match="boom"):
            fail_after_insert()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT n FROM scope_probe")).scalars().all() == [1]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE scope_probe"))


def test_get_session_yields_one_open_session_and_closes_it(
    test_database_url: str,
    engine: object,
    point_settings_at,  # type: ignore[no-untyped-def]
) -> None:
    point_settings_at(test_database_url)
    generator = db_module.get_session()
    session = next(generator)
    assert session.execute(text("SELECT 1")).scalar() == 1
    with pytest.raises(StopIteration):
        next(generator)


def test_engine_and_factory_are_cached_until_disposed(
    test_database_url: str,
    point_settings_at,  # type: ignore[no-untyped-def]
) -> None:
    point_settings_at(test_database_url)
    first = db_module.get_engine()
    assert db_module.get_engine() is first
    assert db_module.get_session_factory() is db_module.get_session_factory()
    db_module.dispose_engine()
    assert db_module.get_engine() is not first


def test_migrate_command_builds_the_schema_from_nothing(
    test_database_url: str,
    point_settings_at,  # type: ignore[no-untyped-def]
) -> None:
    with scratch_database(test_database_url, "backroom_cli_test") as url:
        point_settings_at(url)
        assert run_module.main(["migrate"]) == 0
        assert run_module.main(["migrate"]) == 0  # safe to repeat, as start.sh does on every boot
        with db_module.session_scope() as session:
            tables = session.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ).scalar()
            rates = session.execute(text("SELECT count(*) FROM tax_rates")).scalar()
        assert tables == 52
        assert rates == 4
        db_module.dispose_engine()


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        run_module.main(["frobnicate"])
