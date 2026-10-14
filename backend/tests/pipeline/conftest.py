"""A seeded database for the pipeline tests: fmcg_a, med_a and med_b at full scale.

Seeding takes a couple of minutes, so the database is cached under `backroom_seeded_test` and
rebuilt only when the seed package or the migrations change (a hash of their files is stored in
the database). Tests that run the pipeline write plan rows, so every test starts by clearing them.
"""

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import get_session
from app.jobs.migrate import run_migrations
from app.main import create_app
from app.models.intelligence import WeeklyReport
from app.models.tenancy import User
from app.services import pipeline
from seed.model import tenant_uuid
from seed.profiles import DEFAULT_BASE_SEED, DEFAULT_END_DATE, PROFILES
from seed.run import seed_database
from tests import factories

SEEDED_DB = "backroom_seeded_test"
TENANT_KEYS = ("fmcg_a", "med_a", "med_b")
AS_OF = DEFAULT_END_DATE + timedelta(days=1)
ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct-horse-battery-staple-2026"

CLEAR_PLAN_ROWS = (
    "DELETE FROM recommendation_decisions",
    "DELETE FROM report_notes",
    "DELETE FROM weekly_reports",
    "DELETE FROM recommendation_lines",
    "DELETE FROM recommendation_runs",
    "DELETE FROM forecast_values",
    "DELETE FROM forecast_backtests",
    "DELETE FROM forecast_runs",
    "DELETE FROM event_category_effects",
    "DELETE FROM data_quality_issues",
    "DELETE FROM job_runs",
    "DELETE FROM knowledge_chunks WHERE document_id IN (SELECT id FROM knowledge_documents "
    "WHERE doc_type IN ('decision_memory', 'report_narrative'))",
    "DELETE FROM knowledge_documents WHERE doc_type IN ('decision_memory', 'report_narrative')",
    "DELETE FROM purchase_order_lines WHERE recommendation_line_id IS NOT NULL",
)


def seed_hash() -> str:
    digest = hashlib.sha256()
    paths = sorted((ROOT / "seed").rglob("*.py")) + sorted((ROOT / "seed").rglob("*.yaml"))
    paths += sorted((ROOT / "alembic" / "versions").glob("*.py"))
    paths += [ROOT / "app" / "services" / "rollup.py", ROOT / "app" / "engine" / "rollup.py"]
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(f"{TENANT_KEYS}|{DEFAULT_BASE_SEED}|{DEFAULT_END_DATE}".encode())
    return digest.hexdigest()


@dataclass
class PipelineDb:
    url: str
    engine: Engine
    factory: sessionmaker[Session]
    tenants: dict[str, str]  # profile key to tenant id

    def tenant_id(self, key: str):  # type: ignore[no-untyped-def]
        return tenant_uuid(PROFILES[key])

    def session(self) -> Session:
        return self.factory()

    def clear_plans(self) -> None:
        with self.engine.begin() as conn:
            for statement in CLEAR_PLAN_ROWS:
                conn.execute(text(statement))


def _admin(url: str) -> Engine:
    return create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")


def _cached(url: str, expected: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT hash FROM _seed_cache")).first()
            return row is not None and row[0] == expected
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pipeline_db(test_database_url: str) -> Iterator[PipelineDb]:
    url = make_url(test_database_url).set(database=SEEDED_DB).render_as_string(hide_password=False)
    wanted = seed_hash()
    admin = _admin(url)
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": SEEDED_DB}
        ).scalar()
    if not exists or not _cached(url, wanted) or os.environ.get("RESEED_PIPELINE_DB"):
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{SEEDED_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{SEEDED_DB}"'))
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
            [PROFILES[k] for k in TENANT_KEYS],
            1.0,
            DEFAULT_END_DATE,
            DEFAULT_BASE_SEED,
            reset=False,
            knowledge=False,
            password=PASSWORD,
        )
        assert code == 0
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE _seed_cache (hash text)"))
            conn.execute(text("INSERT INTO _seed_cache VALUES (:h)"), {"h": wanted})
        engine.dispose()
    admin.dispose()
    engine = create_engine(url, pool_size=4, max_overflow=2)
    db = PipelineDb(
        url,
        engine,
        sessionmaker(bind=engine, expire_on_commit=False, autoflush=False),
        {k: str(tenant_uuid(PROFILES[k])) for k in TENANT_KEYS},
    )
    yield db
    engine.dispose()


@pytest.fixture
def seeded_plans(pipeline_db: PipelineDb) -> PipelineDb:
    """The seeded database with every plan row removed, for a test that runs the pipeline."""
    pipeline_db.clear_plans()
    return pipeline_db


def monday_before(day: date) -> date:
    return day - timedelta(days=day.weekday())


API = "/api/v1"
JOB_TOKEN = "test-job-token-0123456789abcdef0123456789"


@dataclass
class Api:
    db: PipelineDb
    client: TestClient
    a: dict[str, str]  # fmcg_a owner headers
    b: dict[str, str]  # med_a owner headers
    report_a: str
    report_b: str

    def get(self, path: str, headers: dict[str, str] | None = None, **kw: Any) -> Any:
        return self.client.get(f"{API}{path}", headers=headers or self.a, **kw)

    def post(
        self, path: str, json: Any = None, headers: dict[str, str] | None = None, **kw: Any
    ) -> Any:
        return self.client.post(f"{API}{path}", json=json, headers=headers or self.a, **kw)

    def put(self, path: str, json: Any, headers: dict[str, str] | None = None) -> Any:
        return self.client.put(f"{API}{path}", json=json, headers=headers or self.a)

    def lines(self, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            body = self.get(
                f"/reports/{self.report_a}/lines", params={"page": page, "page_size": 200, **params}
            ).json()
            out += body["items"]
            if len(out) >= body["total"]:
                return out
            page += 1


@pytest.fixture(scope="module")
def planned(pipeline_db: PipelineDb) -> PipelineDb:
    pipeline_db.clear_plans()
    for key in ("fmcg_a", "med_a"):
        outcome = pipeline.run_pipeline(
            pipeline_db.factory, pipeline_db.tenant_id(key), AS_OF, "light"
        )
        assert outcome.status == "succeeded", outcome.error
    return pipeline_db


@pytest.fixture(scope="module")
def api_module(planned: PipelineDb) -> Iterator[Api]:
    settings = Settings(
        app_env="test",
        database_url=planned.url,
        cors_origins=["http://localhost:5173"],
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        rate_limit_enabled=False,
        job_token=JOB_TOKEN,
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app(settings)

    def override() -> Iterator[Any]:
        with planned.factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    app.state.session_factory = planned.factory
    with planned.session() as s:
        owners = {
            key: s.scalars(select(User).where(User.tenant_id == planned.tenant_id(key))).one()
            for key in ("fmcg_a", "med_a")
        }
        reports = {
            key: str(
                s.scalars(
                    select(WeeklyReport.id).where(
                        WeeklyReport.tenant_id == planned.tenant_id(key), WeeklyReport.is_current
                    )
                ).one()
            )
            for key in ("fmcg_a", "med_a")
        }
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Api(
            planned,
            client,
            factories.auth_headers(settings, owners["fmcg_a"]),
            factories.auth_headers(settings, owners["med_a"]),
            reports["fmcg_a"],
            reports["med_a"],
        )


@pytest.fixture
def api(api_module: Api) -> Iterator[Api]:
    """The shared API with decisions, notes and draft orders removed after each test."""
    yield api_module
    with api_module.db.engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendation_decisions"))
        conn.execute(text("DELETE FROM report_notes"))
        conn.execute(
            text("DELETE FROM purchase_order_lines WHERE recommendation_line_id IS NOT NULL")
        )
        conn.execute(text("DELETE FROM purchase_orders WHERE source = 'recommendation'"))
        conn.execute(text("DELETE FROM idempotency_keys"))
