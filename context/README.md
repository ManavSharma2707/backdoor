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

Built in Prompt 2.

| File | What it is |
|---|---|
| `backend/app/engine/` (Prompt 4) | Also `rollup`, `demand_class`, `dq`, `methods/`, `event_effects`, `forecast`, `backtest`, `selection`, `inventory_state`, `expiry`, `replenishment`, `risk`, `budget`, `plan`, `report_builder`, `deadstock` |
| `backend/app/services/` (Prompt 4) | `rollup`, `dq_service`, `plan_data`, `forecast_store`, `plan_compute`, `pipeline`, `backfill`, `backfill_docs`, `report_service`, `decision_service`, `insight_service`, `scenario`, `jobs`, `export/` (pdf, xlsx, csv) |
| `backend/app/jobs/` (Prompt 4) | `run` (migrate, openapi, monday, backfill, simulate-week, reset-password), `monday`, `accounts` |
| `backend/app/assets/fonts/` | IBM Plex fonts and the OFL licence for PDF export |
| `backend/seed/accuracy.py`, `backend/reports/synthetic_accuracy.md` | Synthetic accuracy grading and its generated report |
| `.github/workflows/monday-job.yml` | Scheduled full Monday run |
| `backend/tests/pipeline/` | Pipeline, API, export and scenario tests on a cached seeded database, plus the golden file |
| `backend/openapi.json` | Generated API contract. `python -m app.jobs.run openapi` rewrites it, a test fails when it is stale |
| `backend/app/core/security.py`, `deps.py`, `ratelimit.py`, `audit.py`, `idempotency.py`, `pagination.py` | Passwords and tokens, tenant context and `require_role`, limits, audit writer, idempotent POST wrapper, paging and sort helpers. `db.py` gained `transaction` and `advisory_lock` |
| `backend/app/assets/common_passwords.txt` | Common password list used by the password policy |
| `backend/app/engine/` | Pure rules: `ledger_rules` (signs, average cost, FEFO), `sales_math` (inclusive GST, discount split, refunds), `po_rules` (state machine, overdue, price variance), `lead_time`, `term_rules` |
| `backend/app/services/` | `auth_service`, `settings_service`, `catalogue_service`, `supplier_service`, `ledger` (only writer of movements and balances), `sales_service`, `purchasing_service`, `inventory_service`, `reconciliation`, `common` |
| `backend/app/api/v1/` | `auth`, `settings`, `catalogue`, `suppliers`, `sales`, `purchasing`, `inventory`, mounted in `router.py` |
| `backend/app/schemas/` | Request and response models per domain, `common.py` has the money and quantity types |
| `backend/tests/api/helpers.py` | Stock, batch and bill helpers for API tests. `conftest.py` has `committed` for concurrency tests |
| `backend/tests/integration/test_ledger_properties.py` | 200 sequence stateful property test of the ledger invariants |


Built in Prompt 3. Everything is under `backend/seed/` (run with `python -m seed.<module>` from `backend/`).

| File | What it is |
|---|---|
| `seed/catalogs/*.yaml` | The four reviewable catalogues (suppliers, categories, products with GST code, pack rules and demand traits). Rewritten by `python -m seed.catalog.builder` from the templates in `seed/catalog/` |
| `seed/scenarios.yaml` | Planted scenarios S01 to S21 per tenant with SKUs and expected engine behaviour. Written by a full scale `seed.run` and compared with the plan by a test |
| `seed/realism_report.md` | Generated realism numbers per tenant (`python -m seed.realism`) |
| `seed/run.py` | Seed CLI: generate in memory, then bulk load. `--tenants --scale --end-date --seed --reset --no-knowledge` |
| `seed/generate.py`, `sim.py`, `demand.py`, `pricing.py`, `scenarios.py`, `traits.py`, `rng.py`, `model.py`, `profiles.py` | The generator: tenant profiles, seeded streams, category traits, price and promotion timelines, true demand, scenario planner, the day by day simulation |
| `seed/loader.py`, `schema.py`, `static_rows.py`, `accounts.py` | COPY loader, column orders, catalogue side rows, SQL rollup fallback (replaced in P4.24), owner users, settings and budgets |
| `seed/corpus/generator.py` | Knowledge corpus text from templates (supplier notes, medical operational notes, app glossary and guides) and the chunker |
| `seed/validate.py`, `size_report.py`, `realism.py`, `checksum.py` | Validators, size table, realism report, determinism checksum |
| `backend/tests/seed/` | Catalogue tests, and DB backed tests at scale 0.1 (session fixture seeds all four tenants into a throwaway database) |
| `backend/alembic/versions/0012_movement_reversal_index.py` | Partial index on `inventory_movements.reverses_movement_id` (a reset took minutes without it) |
