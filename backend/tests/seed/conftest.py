"""A small seeded database (scale 0.1, all four tenants) shared by the seed tests."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.jobs.migrate import run_migrations
from seed.generate import Generated, generate_tenant
from seed.profiles import DEFAULT_BASE_SEED, DEFAULT_END_DATE, PROFILES, Profile, history_start
from seed.run import seed_database
from tests.conftest import scratch_database

SCALE = 0.1
SEED_PASSWORD = "correct-horse-battery-staple-2026"
END = DEFAULT_END_DATE
START = history_start(END)
AS_OF = END + timedelta(days=1)


@dataclass
class Seeded:
    url: str
    engine: Engine
    settings: Settings
    generated: dict[str, Generated]

    def session(self) -> Session:
        return Session(self.engine)


@pytest.fixture(scope="session")
def generated() -> dict[str, Generated]:
    """The four tenants generated in memory, once."""
    return {k: generate_tenant(p, DEFAULT_BASE_SEED, END, SCALE) for k, p in PROFILES.items()}


@pytest.fixture(scope="session")
def seeded(test_database_url: str, generated: dict[str, Generated]) -> Iterator[Seeded]:
    with scratch_database(test_database_url, "backroom_seed_test") as url:
        run_migrations(url)
        settings = Settings(
            app_env="test",
            database_url=url,
            argon2_time_cost=1,
            argon2_memory_cost_kib=8,
            argon2_parallelism=1,
            rate_limit_enabled=False,
            _env_file=None,  # type: ignore[call-arg]
        )
        code = seed_database(
            url,
            settings,
            list(PROFILES.values()),
            SCALE,
            END,
            DEFAULT_BASE_SEED,
            reset=False,
            knowledge=True,
            password=SEED_PASSWORD,
        )
        assert code == 0
        engine = create_engine(url)
        try:
            yield Seeded(url, engine, settings, generated)
        finally:
            engine.dispose()


def profile_of(key: str) -> Profile:
    return PROFILES[key]
