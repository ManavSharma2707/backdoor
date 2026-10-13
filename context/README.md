# Context index

These files are the source of truth for building Backroom. Keep them current. Read order for a fresh session: `../CLAUDE.md`, `memory.md`, `progress.md`, then the specs for your task.

| File | What it holds |
|---|---|
| `architecture.md` | Product principles, system design, repo layout, backend and frontend structure, every feature in detail (F01 to F19), data flows, config, performance budgets |
| `database.md` | Full normalized PostgreSQL schema, constraints, indexes, views, RLS, migrations plan, size budget, reconciliation queries |
| `engine-spec.md` | Forecasting methods, backtesting, event effects, replenishment formulas, expiry and FEFO, dead stock, budget allocation, data checks, Monday pipeline |
| `report-spec.md` | Monday report content, JSON snapshot shape, PDF, Excel and CSV layouts |
| `api-spec.md` | REST conventions, every endpoint, errors, idempotency, SSE chat protocol |
| `seed-data-spec.md` | Four synthetic tenants, simulation model, SKU catalogues, scenarios, volumes, validation |
| `india-calendar.md` | Festival and season calendar for 2025 to 2027 with verification flags, windows, category effects |
| `agents-spec.md` | Chatbot features, tools, RAG corpus, LangGraph design, agent workflows, guardrails, evals |
| `security.md` | Auth design, tokens, cookies, RLS, tenant isolation, threat model, audit events |
| `libraries.md` | Every library, version policy, the exact APIs and gotchas to use |
| `ui-design-system.md` | Tokens, typography, components, charts, layout, anti-template checklist |
| `ui-copywriting.md` | Voice, banned words, punctuation rules, term mapping, microcopy patterns |
| `ui-screens.md` | Screen by screen specification |
| `testing-strategy.md` | Test layers, invariants, golden tests, CI |
| `deployment.md` | Docker, Supabase, Render, Vercel, GitHub Actions, env vars, free-tier constraints |
| `progress.md` | Checklist for the whole build, grouped by prompt |
| `memory.md` | Locked decisions, defaults, decision log, pinned versions, gotchas, session handoff |

Adding a file? Add a row here.

## Code files a future session must know about

Built in Prompt 1. Paths are from the repo root.

| File | What it is |
|---|---|
| `Makefile` | Every developer command (`make help`). Host `uv` for lint, types and tests, `docker compose` for the stack |
| `docker-compose.yml`, `backend/Dockerfile`, `backend/start.sh` | Local stack (db, api dev target, placeholder web) and the production image. `start.sh` runs `python -m app.jobs.run migrate`, then uvicorn |
| `scripts/db_init.sql` | Creates `backroom_test` and the extensions when the db volume is first made |
| `scripts/check_copy.py` | Copy rules: long dashes, banned words, exclamation marks, emoji. Runs in CI, pre-commit and `make check-copy`. Imports the banned list from `backend/app/core/text.py` |
| `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | Local hooks and the CI workflow (backend, copy, frontend switched off until P5.13) |
| `backend/pyproject.toml`, `backend/uv.lock` | Dependencies (runtime, `ml`, `agents`, `dev` groups), ruff, strict mypy for `app.core` and `app.engine`, pytest markers, coverage |
| `backend/app/main.py` | `create_app(settings)` factory and the module level `app` |
| `backend/app/core/` | `config` (settings, production checks), `logging` (JSON, redaction), `clock` (only reader of the system clock, `FakeClock`), `money`, `timeutil` (IST, Monday weeks), `text` (`humanize_text`, `BANNED_WORDS`), `errors` and `messages` (envelope, codes), `middleware` (request id, security headers, catch-all 500), `db` (engine, sessions), `repo` (`TenantRepo`) |
| `backend/app/models/` | All 51 tables. `base.py` has the naming convention, `TenantMixin`, `composite_fk`, `tenant_unique`, `enum_check` |
| `backend/alembic/versions/0001` to `0010` | The schema. `0010` holds RLS, revokes and views |
| `backend/app/jobs/` | `run.py` (CLI, only `migrate` so far), `migrate.py` (alembic under an advisory lock, `head_revision`), `reference_data.py` (GST slabs and the India calendar upsert) |
| `backend/tests/conftest.py`, `backend/tests/factories.py` | Test database, rollback `db` fixture, `rejected()`, `scratch_database()`, `two_tenants`, plain factory functions |
