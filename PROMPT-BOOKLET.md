# Backroom prompt booklet

This file is for you, the human. Claude Code does not read it.

Eight prompts build the whole product. Run them in order, one per fresh Claude Code session, from the repo root. Each prompt is self contained: it tells Claude Code what to read, what to build, how to commit, and when to stop.

## How to use

1. Create the repo folder, copy `CLAUDE.md` and the `context/` folder into it, run `git init` and make the first commit yourself (`chore: add project context files`).
2. Open Claude Code in the repo root. Paste Prompt 1 completely. Wait for it to finish.
3. Check the gate list at the end of the prompt (Claude Code prints the results). Look at `git log` and `progress.md`.
4. Start a **new session** for the next prompt. Do not continue an old session across prompts.
5. If a session runs out of context halfway, start a new one and paste the short **Resume prompt** at the end of this file. It picks up from `progress.md` and `memory.md`.
6. You push to GitHub yourself, after reviewing. Claude Code never pushes.

Things only you can do (the prompts tell Claude Code to stop and list them):
- Create the Supabase project, Render service, Vercel project, GitHub repo and secrets (Prompt 8 gives a checklist).
- Get a Gemini API key from Google AI Studio and put it in `.env` (needed from Prompt 7).
- Choose the demo owner password and put it in `.env` as `DEMO_OWNER_PASSWORD` (needed from Prompt 3).

Expected effort: Prompts 1 to 4 are the heaviest. Do not rush them. Prompt 4 is the heart of the project.

---

## Shared rules (already in CLAUDE.md, repeated so no prompt can drift)

- Read `CLAUDE.md`, `context/memory.md`, `context/progress.md`, `context/README.md` first, then the specs the prompt names.
- Specs are the source of truth. Amend them when reality differs, and log it in `memory.md`.
- Commit only. Never push. No tags. No remotes. Bundled, formal Conventional Commits, about 4 to 8 per prompt, no co-author trailers, never one file spam.
- No em dashes or en dashes anywhere. `python scripts/check_copy.py` must pass before every commit.
- Tick `progress.md` with dates. Update `memory.md` (decisions, pinned versions, gotchas, handoff). Update `libraries.md` when an API surprised you.
- Do not search the web for library usage. Use `libraries.md`. Check versions with the package manager only.

---

# Prompt 1: Foundation and database

```
You are starting the Backroom project. This is Prompt 1 of 8: foundation and database. No application features yet, only the base everything else stands on.

STEP 0. ORIENT
Read, in this order and completely: CLAUDE.md, context/memory.md, context/progress.md, context/README.md, context/architecture.md, context/database.md, context/libraries.md, context/security.md (sections on secrets, headers, tenant isolation), context/api-spec.md (conventions and error envelope only), context/deployment.md (compose, Dockerfile, env tables), context/testing-strategy.md (fixtures, CI), context/ui-copywriting.md (enforcement section only). Run git status and git log --oneline -20. Then tell me in 3 to 6 lines what exists and what you will do. Do not wait for an answer.

GOAL
A repo where `make up` starts Postgres (pgvector), the API and a placeholder web container; `make migrate` builds the entire schema from database.md; health endpoints respond; tests, lint, types and the copy check run in CI. Group P1 in progress.md is the checklist. All of it must be done.

IN SCOPE
Everything in progress.md group P1 (P1.01 to P1.16).

OUT OF SCOPE
Auth endpoints, business endpoints, engine, seed data, frontend code beyond a placeholder container. Do not start them.

TASKS
1. Repo skeleton exactly as in architecture.md section on repo layout, plus .gitignore (env files, backups, node_modules, venvs, build output, reports), .editorconfig, .env.example with every variable from deployment.md (no real values).
2. Backend project with uv: pyproject.toml with the dependency groups from libraries.md (runtime, ml, agents, dev). Pin by letting uv resolve, then record exact versions in memory.md "Pinned versions". Configure ruff, mypy (strict on app/engine and app/core), pytest markers (agent_eval_live), coverage.
3. Docker: multi stage backend Dockerfile with libgomp1, non-root user, start.sh as in deployment.md; docker-compose.yml with db (pgvector/pgvector:pg16, healthcheck, init script creating the test database and extensions vector, citext, pg_trgm, pgcrypto if the spec lists it), api, web placeholder. Named volume for data.
4. Core modules per architecture.md: config (pydantic-settings, fail fast in production on weak or missing secrets, CORS origins list), logging (structlog JSON, redaction of authorization, cookie, password, token, api key fields), clock (FakeClock for tests), money (Decimal helpers, paisa rounding, ROUND_HALF_UP), timeutil (IST helpers, week start Monday), text (humanize_text that strips the two long dash characters, rewrites banned words per ui-copywriting.md, collapses double spaces; with tests).
5. Database layer: engine and session factory sized for the Supabase session pooler (pool settings in deployment.md), TenantRepo base class that always filters by tenant_id and refuses calls without it, models/base.py with naming convention, TenantMixin and the composite tenant foreign key helper.
6. Every SQLAlchemy model in database.md, in the module layout from architecture.md. Follow column names, types, CHECK constraints, partial unique indexes and defaults exactly. If database.md has an error or ambiguity, fix the spec and log it in memory.md.
7. Alembic: env.py reading the same settings, migrations 0001 to 0010 as listed in database.md (extensions, tables by domain, triggers such as updated_at and audit log immutability, views, RLS deny-all with revoked grants, HNSW and GIN indexes). Exclude LangGraph checkpoint tables from autogenerate. Verify `alembic upgrade head`, `downgrade base`, `upgrade head` all work on an empty database. Autogenerate must show no diff after upgrade.
8. Reference data: idempotent upsert of tax rates and calendar events (from india-calendar.md) run at the end of migration or via `python -m app.jobs.run migrate`. Mark unverified dates is_verified=false.
9. FastAPI app factory: request id middleware, security headers per security.md, CORS from settings, global exception handlers producing the error envelope from api-spec.md, /health (liveness) and /health/ready (database check), OpenAPI metadata. No auth yet.
10. Makefile with every target in CLAUDE.md section 7. scripts/check_copy.py exactly as in ui-copywriting.md enforcement (scan the places listed, fail on U+2014 and U+2013 in context/**, banned words and exclamation marks in copy files). Pre-commit config running ruff, check_copy.
11. Tests: conftest.py with a session scoped test database, rollback per test with savepoint mode, factories, two_tenants fixture. Tests listed in P1.13: migration round trip, cross tenant composite FK rejection for at least five parent child pairs, CHECK constraints, partial unique indexes, audit log update and delete rejected, RLS deny test using a role with no grants, health endpoints, error envelope, humanize_text, money rounding, week start helper.
12. CI: .github/workflows/ci.yml as in testing-strategy.md section 9 (backend job with pgvector service, copy job; frontend job present but skipped until Prompt 5 via an if condition).

COMMIT PLAN (bundled, formal, no push)
- chore(infra): add repo skeleton, tooling configuration and docker setup
- feat(core): add configuration, logging, clock, money, time and text helpers with tests
- feat(db): add sqlalchemy models and tenant repository base
- feat(db): add alembic migrations, reference data and database constraint tests
- feat(api): add application factory, error envelope and health endpoints
- ci(infra): add makefile targets, copy check, pre-commit and ci workflow
- docs(context): record pinned versions, gotchas and progress for prompt 1
Adjust if natural groupings differ, but keep bundles meaningful and never commit a failing state.

VERIFICATION GATE (run all, show results, fix until green)
- docker compose build && make up, then curl localhost:8000/health and /health/ready
- make migrate on a fresh volume, then alembic downgrade base and upgrade head again
- alembic check shows no pending diff
- make lint, make typecheck, make test (show test count and coverage for app/core)
- python scripts/check_copy.py
- git status clean, git log shows the bundled commits, nothing pushed (there is no remote)

CONTEXT UPDATES (mandatory)
progress.md: tick P1.01 to P1.16 with dates, update status header. memory.md: pinned versions, gotchas found, decisions made, rewrite Session handoff (next step: Prompt 2). README.md in context: add any new files. libraries.md: fix anything that was wrong.

STOP CONDITIONS
Stop and report instead of guessing if: a table in database.md cannot be created as written, the pgvector image is unavailable, or Docker cannot run in this environment (then do everything possible without Docker, run tests against a local Postgres if one exists, and say exactly what was not verified).

FINAL REPORT
Under 15 lines: what now works, commands to try, test counts, anything the specs got wrong and how you fixed it, what Prompt 2 starts with.
```

---

# Prompt 2: Auth and transactional core

```
This is Prompt 2 of 8: authentication and the transactional core (catalogue, suppliers, sales, purchasing, inventory ledger). Prompt 1 is complete and committed.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: security.md, api-spec.md, database.md, architecture.md (backend structure and flows), testing-strategy.md (sections 3, 5), libraries.md (auth, rate limit, FastAPI, SQLAlchemy sections). Run git status and git log --oneline -20. Verify that make up, make migrate and make test are green before you start; if not, fix that first in its own commit. Report in 3 to 6 lines, then continue.

GOAL
A complete, secure authentication system and every transactional endpoint a retailer needs to run the business day to day, built on a correct stock ledger. Group P2 in progress.md (P2.01 to P2.18).

IN SCOPE
Auth, tenant context, rate limiting, audit logging, settings, catalogue, suppliers and terms, ledger, sales, returns, purchasing and receipts, inventory endpoints, idempotency, tests.

OUT OF SCOPE
Seed data, forecasting, reports, agents, frontend.

TASKS
1. Passwords: argon2id via argon2-cffi with parameters from security.md, policy (length 12 or more, common password list file, not equal to email), rehash on login when parameters change, lockout (5 failures, 15 minutes) stored on the user row, constant time path that hashes a dummy value for unknown emails so response timing does not leak existence.
2. Tokens: PyJWT access token 15 minutes with claims from security.md (sub, tid, role, jti, iat, exp, iss, aud), strict validation (algorithm pinned, required claims). Refresh tokens: opaque random value, only the hash stored, family id, rotation on every use, reuse detection revokes the whole family, short grace window for concurrent refresh as specified, 14 day expiry, httpOnly Secure SameSite=Lax cookie scoped to the refresh path, cookie flags driven by settings so local http works.
3. Auth endpoints exactly as api-spec.md: login, refresh, logout, logout-all, me, change-password (revokes other sessions). Registration and demo login exist but return 404 unless their flags are on. Generic error messages. CSRF defence for the refresh endpoint as specified in security.md.
4. slowapi rate limits (login per IP and per email, refresh, general), 429 with Retry-After in the error envelope. Audit log service writing the events listed in security.md (login success and failure, lockout, token reuse, password change, settings change, void, adjustment, write off, PO status changes). Audit rows are append only.
5. Dependencies: get_current_user, TenantContext (tenant_id and user id from the token only), require_role. Every repository call receives TenantContext.
6. Settings endpoints (business_settings read and update with validation ranges from engine-spec.md and api-spec.md, audit each change).
7. Catalogue: categories, products (create, update, deactivate, search by name or SKU or barcode using pg_trgm, filters), product prices history, equivalents (medical, no clinical data), tax rates list. Server side validation for pack size, MOQ, shelf life rules from database.md.
8. Suppliers and effective dated terms: primary uniqueness, overlapping range rejection, lead time resolution helper (product level, supplier level, default 3 days) with tests.
9. Ledger service: the only code that writes inventory_movements and stock_balances. Row locks on balances, weighted average cost on receipt, FEFO allocator with batch override, no negative balances, movement types and sign rules exactly as database.md. Write it as small pure helpers plus one transactional class.
10. Sales: create with idempotency key, FEFO split across batches, server computed totals and tax per line, payment mode, duplicate bill number conflict, duplicate warning heuristic from api-spec.md, void (reversal movements, original rows untouched). Returns with dispositions (restock, damaged, expired) and quantity limits.
11. Purchasing: purchase orders and lines, state machine (draft, sent, partially received, received, cancelled) with allowed transitions, receipts creating batches for medical tenants, exception rules (over receipt, short receipt, price variance flag), overdue detection, supplier return.
12. Inventory endpoints: stock levels with filters, batches with expiry days, movements list, adjustments (reason required), write off, stock counts (start, submit, approve with variance movements), stockout interval list, reconciliation endpoint comparing balances with the movement sum.
13. Idempotency: table use and middleware or dependency per api-spec.md: same key and same body returns the stored response, same key and different body returns 422, keys expire.
14. Tests: auth suite (rotation, reuse, grace, lockout, timing path via spy, cookie attributes, flags default off, expired and tampered tokens). Hypothesis property tests for ledger invariants 1 to 5 in testing-strategy.md section 3. For every route: 401 test and a two tenant isolation test. Error envelope tests. Concurrency test: two simultaneous sales of the last unit, exactly one succeeds.
15. Generate OpenAPI JSON into the repo path named in architecture.md and check it for the error envelope and tags.

COMMIT PLAN
- feat(auth): add password hashing, token issuance, rotation and auth endpoints
- feat(auth): add rate limiting, audit logging, tenant context and role dependency with tests
- feat(catalogue): add settings, categories, products, equivalents and tax endpoints
- feat(purchasing): add suppliers, effective dated terms and lead time resolution
- feat(ledger): add stock ledger service, FEFO allocator and balances with property tests
- feat(sales): add sales, returns and voids with idempotency
- feat(purchasing): add purchase orders, receipts and exception rules
- feat(inventory): add stock, batch, adjustment, count and reconciliation endpoints
- docs(context): update specs, progress and memory for prompt 2
Merge bundles if that is cleaner. Each commit green.

VERIFICATION GATE
- make lint, make typecheck, make test; show coverage: auth and ledger at least 90 percent
- Reconciliation property test passes with at least 200 generated sequences
- Manual smoke with curl: login, create product, receive stock, sell, void, check stock and reconcile
- check_copy passes; no secrets in git diff
- OpenAPI file regenerated and committed

CONTEXT UPDATES
progress.md P2.01 to P2.18 ticked with dates. memory.md: decisions (for example grace window length, idempotency TTL), pinned versions, gotchas, handoff for Prompt 3. api-spec.md and database.md amended where reality changed.

STOP CONDITIONS
Stop and ask only if a security decision in security.md conflicts with another spec and the choice is hard to reverse. Otherwise decide, log it, and continue.

FINAL REPORT
Under 15 lines: what works, how to try it, test counts and coverage, deviations from spec and why.
```

---

# Prompt 3: Seed data

```
This is Prompt 3 of 8: realistic synthetic data for four Indian retail businesses. The data quality decides how convincing the whole product is, so spend effort here.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: seed-data-spec.md, india-calendar.md, database.md (all tables the loader writes, plus movement semantics and reconciliation SQL), engine-spec.md sections 1 to 4 (definitions, rollup, classification) so the data suits the engine, agents-spec.md section on the knowledge corpus, testing-strategy.md (seed tests). Run git status and git log --oneline -20, confirm make test is green. Report in 3 to 6 lines, then continue. DEMO_OWNER_PASSWORD must exist in .env; if it does not, stop and tell me to set it (12 or more characters), do not invent one.

GOAL
A deterministic generator that fills four tenants (fmcg_a 92 SKUs, fmcg_b 118, med_a 150, med_b 152) with 78 weeks of history (2025-04-14 to 2026-10-11), consistent with the ledger, with planted scenarios S01 to S21 the engine must handle, a knowledge corpus, and a validator. Group P3 (P3.01 to P3.13).

IN SCOPE
Seed package, catalogue YAML, calendar date verification, simulation, loader, validators, corpus text, tests.

OUT OF SCOPE
Engine code, reports, agents, frontend. Do not mention any city, district or state name in any seeded name, address, note or corpus text. Businesses have fictional names and no location.

TASKS
1. Catalogue YAML per tenant, matching the per category counts in seed-data-spec.md exactly. Fictional brand names that do not imitate real brands closely. Realistic Indian pack sizes, MRPs, margins, GST slab mapping per D-042 (representative only), HSN-like codes are optional and must not claim accuracy. Medical: real generic names, strengths and forms, schedule flag as per spec, no dosing or clinical text, shelf life by category, batch rules. Suppliers (5 to 9 per tenant) with terms, MOQs, pack rules, lead times with variability, payment terms.
2. Verify the calendar: for every event marked verify in india-calendar.md, check two independent sources with the web search tool (this is the one place web search is allowed in this prompt), update india-calendar.md and the reference rows, set is_verified, log the sources and results in memory.md. If two sources disagree by a day, keep the conservative window and note it.
3. Generator core: seeded numpy RNG (one stream per tenant and purpose so changes do not shift unrelated data), true demand model: base rate by product and category, weekday and day of month pay cycle effects, seasonality, event effects with product category multipliers per india-calendar.md, promotions, price elasticity, trend, new product ramp, noise (negative binomial for count data). Store true demand in synthetic_true_demand so accuracy can be graded later.
4. Simulation loop, day by day: demand, stock limited sales (stockouts truncate sales, so demand is censored), bills built from baskets with realistic lines per bill, payment modes, returns, small adjustments, owner ordering policy (imperfect, so the engine has something to improve), purchase orders with lead time variability and partial and late deliveries, receipts, stock counts, price changes, promotions. Medical: batches with expiry, FEFO issue, expiry write-offs, supplier returns, near expiry stock build up in chosen products.
5. Scenarios S01 to S21 exactly as specified, recorded in seed/scenarios.yaml with product SKUs and expected engine behaviour. Include the negative cases (a festival with no real uplift, a medical festival with a single occurrence).
6. Bulk loader using COPY for high volume tables, respecting composite FKs and the ledger semantics, then rebuild stock_balances from movements and run the reconciliation SQL. Run the rollup for daily_product_stats if the service exists, otherwise a SQL fallback that Prompt 4 replaces (record this in progress.md as a follow up item).
7. Users and settings: one owner per tenant, emails from seed-data-spec.md, password from DEMO_OWNER_PASSWORD (argon2id through the auth service), business_settings, weekly budgets per scenario.
8. Knowledge corpus generator: supplier documents (terms, notices, scheme circulars), product notes, app help text, written by templates with variation, no dashes, no locations. Text only ingestion into knowledge_documents and chunks without embeddings (Prompt 7 adds embeddings).
9. CLI: python -m app.seed.run with --tenants, --scale, --end-date, --reset, --no-knowledge, --seed; seed.validate; seed.size_report; a determinism checksum command. make seed and make seed-reset call these.
10. Tests at scale 0.1: validators, determinism (same seed twice gives same checksum), scenario presence (each scenario product exists with the planted pattern), ledger reconciliation, no dash characters in any generated text, no location words (keep a small blocklist in the test).
11. Realism report (seed/realism_report.md, generated): per tenant daily sales, basket size, category share, stockout rate, expiry loss share, weekday profile, festival uplift measured on true demand. Fix the generator if numbers look implausible (for example margins above 40 percent for FMCG staples, daily bills far above what a shop of that size could serve).

COMMIT PLAN
- feat(seed): add catalogue definitions and supplier terms for four tenants
- docs(context): record verified festival calendar dates and sources
- feat(seed): add demand model and day by day simulation
- feat(seed): add medical batch logic and planted scenarios
- feat(seed): add bulk loader, users, settings and knowledge corpus text
- feat(seed): add validators, size report, cli and seed tests
- docs(context): record data volumes, realism findings and handoff for prompt 4

VERIFICATION GATE
- make seed-reset with all four tenants completes; record the time
- seed.validate green for all tenants; seed.size_report total under 400 MB, show the table
- Determinism checksum identical across two runs
- Scale 0.1 tests green in CI time (under 3 minutes)
- You can log in as each owner through the API using the env password
- check_copy passes on seed text and YAML

CONTEXT UPDATES
progress.md P3.01 to P3.13. memory.md: actual volumes and sizes in Measurements, verification outcomes, decisions. seed-data-spec.md and india-calendar.md amended with real numbers and dates.

STOP CONDITIONS
If the full seed exceeds 400 MB, reduce lines per bill or history retention in the spec (log it) rather than exceeding the free tier. If a verified date contradicts the spec, update the spec and continue.

FINAL REPORT
Under 15 lines: volumes, sizes, timings, the realism highlights, any dates changed, how to log in as each demo owner (email only, never print the password).
```

---

# Prompt 4: Intelligence engine and report

```
This is Prompt 4 of 8: the intelligence engine and the Monday report. This is the core of the product. Correctness matters more than speed here. Every number must be explainable.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely and slowly: engine-spec.md (all sections), report-spec.md, india-calendar.md, database.md (intelligence tables, views, rollup), api-spec.md (reports, insights, jobs endpoints), seed-data-spec.md (scenarios), testing-strategy.md (sections 3, 4, 6), deployment.md (monday-job workflow), libraries.md (pandas, numpy, scikit-learn, lightgbm, reportlab, xlsxwriter, statistics). Run git status and git log --oneline -20, confirm make seed and make test work. Report in 3 to 6 lines, then continue.

GOAL
Given the seeded data, `python -m app.jobs.run monday --tenant <id>` produces a stored weekly report: forecasts, usable stock, expiry exposure, supplier aware order quantities, budget allocation, risk, stock status, festival effects with evidence, data quality notes, and exports in PDF, Excel and CSV. Group P4 (P4.01 to P4.23).

IN SCOPE
app/engine (pure functions, no DB), services around it, pipeline orchestrator, report builder, endpoints for reports, decisions, notes, PO drafts, insights and dashboard, exports, backfill, GitHub Actions workflow, tests.

OUT OF SCOPE
Frontend, agents and RAG. Provide the Overrides dry run API they will use later.

TASKS (follow engine-spec.md formulas literally; if you find a flaw, fix the spec, log it, add a test)
1. Rollup service: daily_product_stats incremental and rebuildable, with availability flags and censoring, tested against hand computed small cases.
2. Data quality checks with every code from engine-spec.md section 14, each producing structured findings with severity.
3. Demand classification (smooth, erratic, intermittent, lumpy, new, no history) with the thresholds in the spec.
4. Forecast methods as pure functions: seasonal naive, moving average, weekday profile, SES with weekday seasonality, Croston SBA, category prior for new products. Non-negative outputs, no lookahead (property test that future noise does not change a forecast).
5. LightGBM global model with lazy import, row and feature caps, early stopping, deterministic seed, fallback to the ladder on any failure. Light profile never imports it.
6. Event effect learning: per tenant and category ratios on true history with shrinkage, consistency and product count gates, stricter medical gate, application only when gated, evidence stored for the report. Include the negative cases from the seed scenarios.
7. Backtest runner: rolling origin, 12 weekly origins (4 for LightGBM), metrics (WAPE, bias, coverage), per segment selection with the 3 percent parsimony rule, confidence labels, stored in forecast_runs and metrics tables.
8. Inventory state: on hand, usable stock (exclude expired and near expiry as per rules), incoming PO with overdue handling, FEFO expiry simulation over the horizon, expected loss.
9. Replenishment: lead time resolution, protection period, safety stock using statistics.NormalDist, MOQ and pack rounding (default up), expiry cap, spend. Worked example from testing-strategy.md item 6 must pass exactly (raw 17, suggested 20).
10. Risk model (stockout probability, levels), budget allocation (greedy by priority score with D-036 weights, whole packs, partial allocation, shortfall reporting), budget view.
11. Stock status: non-moving versus unverified, slow, new; excess; ABC classification.
12. Report builder: sections and line fields with provenance tags and reason templates in plain humanized English (no dashes), snapshot JSON as in report-spec.md, version handling and is_current flag.
13. Pipeline orchestrator: light and full profiles, per tenant advisory lock, idempotency per week, force creates a new version, transactional persist with rollback on failure, job_runs rows, retention rules, entry points `python -m app.jobs.run migrate|monday|backfill|simulate-week|reset-password` (simulate-week may be a documented stub that Prompt 8 completes; if so, add a progress item).
14. Overrides and dry run function for scenario planning (budget, lead time, demand multiplier, product exclusions) that never writes plan rows.
15. Endpoints: reports list and detail, line decisions (approve, edit with reason, reject) with totals recomputed, notes, PO drafts from approved lines (blocked line handling), insights and dashboard queries from api-spec.md, job trigger endpoint with the light profile and concurrency guard.
16. Exports: ReportLab PDF with registered IBM Plex TTFs (bundle fonts in the repo under the path in architecture.md), Excel with XlsxWriter (formulas with cached values, frozen panes, number formats), CSV with BOM. Layouts per report-spec.md. Cross format totals equal to the paisa. Festival note section in each.
17. Backfill 8 weekly plans with synthetic decisions so insights have history; records which are synthetic.
18. Tests: property tests 6 to 11 in testing-strategy.md, scenario tests for S01 to S21 located via seed/scenarios.yaml, golden pipeline output for a fixed small seed, export tests, determinism, failure injection rollback test, two tenant tests on new endpoints.
19. Synthetic accuracy report (backend/reports/synthetic_accuracy.md): grade forecasts and event effect recovery against synthetic_true_demand, compare chosen method versus baselines, and report honestly, including tenants or categories where the engine does not beat the baseline. Never present these as customer results (D-040).
20. .github/workflows/monday-job.yml as in deployment.md.

COMMIT PLAN
- feat(forecast): add rollup, data quality checks, classification and forecast methods
- feat(forecast): add lightgbm model, event effect learning and backtest selection
- feat(replenishment): add inventory state, expiry simulation, replenishment, risk and budget allocation
- feat(report): add report builder, pipeline orchestrator, overrides and job entry points
- feat(report): add report, decision, insight and dashboard endpoints
- feat(export): add pdf, excel and csv exports with tests
- test(forecast): add property, scenario and golden tests and synthetic accuracy report
- ci(infra): add monday job workflow
- docs(context): record thresholds, backtest results, timings and handoff for prompt 5

VERIFICATION GATE
- Full monday run for all four tenants; record time and peak memory per tenant (light and full profile); light profile must fit the budget in architecture.md
- Engine coverage at least 85 percent; mypy strict on app/engine
- All scenario tests, property tests, golden test, export tests green
- Open the generated PDF text and the Excel file with openpyxl in a test and print a short sample of lines in your report
- Run twice: identical output; run with force: version 2
- check_copy passes on generated report text

CONTEXT UPDATES
progress.md P4.01 to P4.23. memory.md: thresholds actually used, backtest results table in Measurements, timings, decisions, handoff for Prompt 5. engine-spec.md and report-spec.md amended wherever implementation taught you something.

STOP CONDITIONS
If the engine does not beat the baseline for a segment, do not tune on the test origins. Report it, keep the baseline as the selected method (that is what the parsimony rule does), and say so in the accuracy report.

FINAL REPORT
Under 20 lines: timings, accuracy highlights and weak spots, scenario results, anything in the specs changed, what Prompt 5 starts with.
```

---

# Prompt 5: Frontend foundation and core screens

```
This is Prompt 5 of 8: the React frontend foundation and the everyday screens. The look and the words matter as much as the code. The UI must not look generated, and it must contain no em dashes or en dashes anywhere.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: ui-design-system.md (including the anti-template checklist), ui-copywriting.md, ui-screens.md (global behaviours, login, overview, products, sales, purchases, stock, settings), api-spec.md (the endpoints these screens use), libraries.md (frontend sections), architecture.md (frontend structure), security.md (token storage, CSP), testing-strategy.md (section 8). Run git status and git log --oneline -20, confirm the backend runs with seeded data (make up, make seed). Report in 3 to 6 lines, then continue.

GOAL
A fast, calm, ledger style interface where an owner can sign in, see an overview, manage products, enter sales quickly, record purchases and receipts, and manage stock. Group P5 (P5.01 to P5.15). The Monday plan and insights come in Prompt 6, the assistant in Prompt 7; leave clean extension points.

IN SCOPE
Vite React TypeScript project, Tailwind v4 theme tokens, API client, auth, formatting, primitives, shell, login, overview, products, sales, purchases, stock, settings, tests, vercel.json, CI frontend job.

OUT OF SCOPE
Plan screens, insights screens, assistant UI. Placeholders for their routes are fine, labelled plainly.

TASKS
1. Project setup per libraries.md: React 19, TypeScript strict, Vite, Tailwind v4 with the @theme tokens copied exactly from ui-design-system.md, self hosted IBM Plex Sans and Mono (woff2 in the repo), React Router, TanStack Query, react-hook-form with zod, ESLint with a custom rule or test that bans dash characters in source strings under src/copy, Prettier, Vitest, Testing Library, MSW, jest-axe. Scripts: dev, build, lint, typecheck, test, openapi-types (generate types from the backend OpenAPI file).
2. lib/api.ts: base URL from env, bearer token from memory only, single flight refresh on 401 then one retry, error envelope parsing into a typed ApiError, request id capture, cold start handling (one retry on timeout, a plain waiting message). lib/auth: login, logout, session restore via refresh cookie on load, route guards. Never store tokens in localStorage or sessionStorage.
3. lib/format.ts: INR with Indian digit grouping, lakh and crore compact form, quantities, dates in IST (dd MMM yyyy), percentages, relative days; thorough unit tests including negative and zero cases. copy/en.ts: all user text, structured by screen, following ui-copywriting.md (voice, term mapping, banned words, no exclamation marks, no asterisks for required fields).
4. UI primitives per ui-design-system.md: button, text input, number input, select, combobox, date picker, tabs, table (dense, sticky header, numeric columns right aligned in Plex Mono), badge, dialog, drawer, tooltip, banner, empty state, skeleton, toast, pack stepper, command palette. Keyboard accessible, visible focus rings, correct roles. A /_ui gallery route (development only) showing every primitive and state.
5. App shell: sidebar, top bar with business name and week, demo strip text from copy, responsive behaviour (collapses to a drawer on small screens). No decorative gradients, no emoji icons, no generic hero sections.
6. Login: email and password, clear errors from the envelope (lockout message with the wait time), cold start message after a few seconds, optional demo buttons only when the backend says demo login is enabled.
7. Overview: the cards and lists specified in ui-screens.md using real endpoints, skeletons and empty states, no fake numbers. Leave the assistant nudge slot empty.
8. Products: list with search and filters, add and edit forms with plain validation messages, detail with tabs (details, stock, batches, price history, sales). Medical specifics shown only for medical tenants.
9. Sales: list, fast entry screen (search, Enter adds a line, Ctrl+Enter saves, stock warning, duplicate warning), bill detail, return and void dialogs with reasons.
10. Purchases: list, new order, detail with status flow, receipt form with batch and expiry entry for medical tenants and exception prompts.
11. Stock: levels, batches and expiry, movements, counts, out of stock history, adjustment dialog.
12. Settings: planning parameters, calendar events list (read and toggle), account and password change, about (synthetic data note).
13. Tests: formatter tests, API client refresh tests, form validation tests, sale entry keyboard flow, a copy test that renders every route with MSW data and asserts no dash characters, no banned words and no exclamation marks, axe tests on login, overview, products and sale entry.
14. vercel.json with the rewrite proxy from deployment.md and security headers. Enable the frontend job in ci.yml.
15. Anti-template review: walk the checklist in ui-design-system.md against every screen. Write the findings and fixes in memory.md. Take screenshots with Playwright (Chromium is installed) into frontend/screenshots (git-ignored) and look at them yourself at 1440 and 390 widths; fix spacing, alignment and overflow problems you see.

COMMIT PLAN
- feat(ui): add frontend project, theme tokens, fonts, api client and formatting helpers
- feat(ui): add component primitives, gallery and application shell
- feat(ui): add login and overview screens
- feat(ui): add products and stock screens
- feat(ui): add sales entry and purchase screens
- feat(ui): add settings screens
- test(ui): add component, copy and accessibility tests and enable frontend ci job
- docs(context): record design review notes, pinned versions and handoff for prompt 6

VERIFICATION GATE
- npm run lint, typecheck, test, build all green; show test counts
- python scripts/check_copy.py (it must also scan frontend/src/copy)
- make up serves the app; log in as a demo owner and complete: add a sale, receive a purchase, adjust stock
- Screenshots reviewed at desktop and mobile widths; list any known visual issues honestly
- Bundle size reported (initial JS gzip), target under 250 KB

CONTEXT UPDATES
progress.md P5.01 to P5.15. memory.md: pinned versions, design review notes, gotchas, handoff. ui-* files amended where the build taught you something (for example a spacing value that needed to change), never loosened to hide a violation.

STOP CONDITIONS
If a screen needs an endpoint that does not exist, add it to the backend with tests in a separate commit and update api-spec.md, then continue.

FINAL REPORT
Under 15 lines: what works, screenshots reviewed, bundle size, known visual gaps, what Prompt 6 starts with.
```

---

# Prompt 6: Monday plan, insights and exports UI

```
This is Prompt 6 of 8: the screens the product is about. The Monday plan screen is the most important screen in the app. An owner should be able to review a whole week of buying in about ten minutes.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: ui-screens.md (Monday plan and insights sections, global behaviours), ui-design-system.md (data display, charts, anti-template checklist), ui-copywriting.md, report-spec.md (sections and fields), api-spec.md (reports, decisions, PO drafts, insights, exports), engine-spec.md section on sections and stock status, india-calendar.md (how events are shown), testing-strategy.md (frontend and e2e). Run git status and git log --oneline -20; confirm that a Monday report exists for each tenant (make job-monday) and the frontend builds. Report in 3 to 6 lines, then continue.

GOAL
The full plan review flow, insights, charts and downloads. Group P6 (P6.01 to P6.12).

IN SCOPE
Plan screens, decision flow, PO creation flow, downloads, insights (six tabs), charts, Explain buttons wired to a stub that Prompt 7 replaces, tests, e2e.

OUT OF SCOPE
The assistant itself. Explain buttons call a clearly marked stub function in one place (lib/assistantBridge.ts) that currently opens a plain message saying the assistant arrives later in dev builds only; in the production build the buttons are hidden until Prompt 7 wires them.

TASKS
1. Plan shell: header with week range, status (creating, ready, reviewed, ordered), week switcher, summary block (lines, spend versus budget, items at risk, expiry exposure), festival note, version badge, creating state with progress polling.
2. Buy tab: dense table per ui-screens.md with filters (category, supplier, risk, confidence) synced to the URL, expandable rows showing the working (forecast, usable stock, incoming, protection period, safety stock, pack and MOQ rounding, expiry cap) in plain language, provenance tags (learned, estimated, from settings, from your data), bulk actions, keyboard navigation.
3. Decisions: approve, edit quantity with the pack stepper (only whole packs, shows rounding reason and spend delta), reject with reason, optimistic updates with rollback on error, totals and budget bar update live, sticky decision footer, undo for the last change.
4. Tabs: Do not buy (with reasons), Watch, Reduce exposure (batch table, write off dialog calling the real endpoint), Festival and season (evidence table, configured effect dialog), Budget (allocation view, shortfall, what was left out), Data notes (findings with severity and links to the fix screen).
5. Create purchase orders: group approved lines by supplier, preview, blocked line handling (missing supplier terms and so on, with a direct link to fix), confirmation, resulting PO links.
6. Downloads: PDF, Excel, CSV through authenticated fetch (never a bare link), correct file names from report-spec.md, progress and error states.
7. Insights: six tabs per ui-screens.md (sales and demand, stock health, expiry, suppliers, forecast accuracy, festival impact) using Recharts with the chart rules from ui-design-system.md (no default Recharts look, direct labels where possible, festival bands from the calendar, Indian number formats, accessible descriptions and data tables behind charts). Honest empty states.
8. Explain buttons on key numbers, wired to the stub, so Prompt 7 only swaps one function.
9. Tests: component tests for filters and URL sync, pack stepper math, decision totals, optimistic rollback, blocked PO lines; copy test extended to the new routes; axe tests on plan and insights; Playwright e2e for login, review and approve lines, create POs, download each export, and a sale entry flow. Run e2e against the seeded stack.
10. Anti-template review of every new screen, screenshots at 1440 and 390 widths, fix what looks off. Record findings in memory.md.

COMMIT PLAN
- feat(ui): add plan shell, buy tab and decision flow
- feat(ui): add plan secondary tabs, purchase order creation and downloads
- feat(ui): add insights screens and charts
- test(ui): add plan and insights component tests and end to end flows
- docs(context): record review notes and handoff for prompt 7

VERIFICATION GATE
- npm run lint, typecheck, test, build green; Playwright e2e green locally
- check_copy passes, including text rendered from backend report strings (the copy test covers it)
- Real flow with the seeded fmcg_a and med_a tenants: approve 10 lines, edit 2, reject 1, create POs, download all three files, open them
- Screenshots reviewed at both widths, issues listed honestly

CONTEXT UPDATES
progress.md P6.01 to P6.12; memory.md review notes and handoff; ui-screens.md amended with any behaviour you refined.

STOP CONDITIONS
If an API field needed by a screen is missing, add it to the backend with tests and update api-spec.md and report-spec.md first.

FINAL REPORT
Under 15 lines: what works, screenshots reviewed, e2e results, visual gaps, what Prompt 7 starts with.
```

---

# Prompt 7: RAG, agents and assistant

```
This is Prompt 7 of 8: the assistant. It explains and investigates. It never invents numbers and never changes anything without an explicit confirm card. Agent steps are stored in our own trace tables and are never shown to users; the user sees only friendly status lines.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: agents-spec.md (every section), security.md (injection, tenant isolation, data sent to Gemini), api-spec.md (chat, threads, actions, SSE protocol), database.md (agent, knowledge, checkpoint tables), libraries.md (langgraph, langchain-google-genai, google-genai, pgvector, sse), ui-screens.md (assistant), ui-design-system.md (assistant components), ui-copywriting.md, testing-strategy.md (section 7). Run git status and git log --oneline -20; confirm the plan flow works. Confirm GEMINI_API_KEY exists in .env; if it does not, build everything against the fake LLM, finish all tests, and tell me clearly that live verification is pending. Report in 3 to 6 lines, then continue.

GOAL
The full assistant: tiered capabilities from agents-spec.md, hybrid RAG, LangGraph orchestration, three core workflows (Monday Analyst, exception investigator, goal driven scenario planner) plus the two polish workflows, interactive UI blocks, and an evaluation harness. Group P7 (P7.01 to P7.15).

IN SCOPE
Backend agent package, tools, RAG, verifier, safety, graph, checkpointer, chat endpoints with SSE, trace tables, workflows, evals, frontend assistant panel and page, wiring of Explain buttons and nudges.

OUT OF SCOPE
Any write action without a confirm card. Any use of real customer data with the free key (D-031). Any clinical or dosing advice (D-041).

TASKS
1. Models: list available Gemini models at runtime with the SDK, choose a fast general model for chat and the embedding model for 768 dimension embeddings (set output dimensionality and L2 normalise), store the choice in settings and memory.md. Never hard code a name that was not listed. Respect free tier quotas from agents-spec.md.
2. LLM wrapper: retry with backoff on transient errors, per user and global limiter, quota exhausted result that the graph turns into the plain fallback, message_text helper for block lists, timeouts, token budget trimming.
3. Knowledge: embed the seeded corpus chunks, ingest decision memory live (approvals, edits and reasons) and report narratives, with tenant and visibility metadata. Embedding batch sizes and rate limits respected, resumable.
4. RAG: hybrid search (pgvector cosine plus full text), reciprocal rank fusion, tenant filter in the SQL itself, visibility filter so internal corpus is never quoted as a source chip unless allowed by agents-spec.md.
5. Tools (all in agents-spec.md): each a typed function using TenantContext, row limits, control character stripping on any free text returned, read only except the proposal tools that create a pending action card. Write a test per tool proving two tenant scoping.
6. Verifier: every number and date in a draft must match a fact in the tool results (with rounding and compact INR forms like 1.8 lakh), reject invented figures, strip dashes, run humanize_text. Safety nodes: clinical and dosing refusal, cross tenant refusal, prompt injection resistance (names and notes are data, not instructions), PII minimisation.
7. LangGraph: custom StateGraph per agents-spec.md (router, specialists, tool loop with caps of 8 LLM steps, 10 tool calls, 45 seconds for chat; 14 steps and 120 seconds for workflows), responder, verifier, one repair attempt then template fallback, Postgres checkpointer (setup() once, excluded from Alembic, RLS enabled afterwards), interrupt and resume for action cards.
8. Endpoints: threads, messages, SSE stream with the event types in api-spec.md (status lines only, blocks, final), feedback, pins, nudges, action confirm and cancel. Rate limits 20 per minute and 200 per day per user. Agent disabled flag and quota fallback.
9. Workflows: Monday Analyst (reads the stored report, produces a briefing with what changed, what to check first, and festival context), exception investigator (explains one line or one anomaly using the working, supplier history and decision memory), goal driven scenario planner (parses a goal such as a lower budget or a longer lead time, calls the Overrides dry run, compares before and after, offers a confirm card to save as a draft). Data quality and supplier prep workflows as polish.
10. Trace tables: agent_runs and agent_steps written for every run (inputs summarised, tools, timings, token counts, verifier results), never returned by any endpoint. Add a test that no response schema includes them.
11. Evals: backend/tests/agents with a fake LLM that scripts tool calls and drafts (CI), the adversarial verifier cases from testing-strategy.md section 7, safety cases, and a live suite marked agent_eval_live that writes backend/tests/reports/agent_eval.md. Run the live suite once if a key exists and report the grounding pass rate and failures honestly.
12. Frontend: assistant panel (slide over) and full page, message blocks (text, number table, mini chart, compare, product card, action card, source chips, follow ups), starters per screen, Explain buttons now calling the real bridge, nudges on overview, a short product tour, the UI actions whitelist (navigate, open product, filter plan; nothing else), fallback UI when quota is out or agents are disabled, streaming with stop button. Copy follows ui-copywriting.md; assistant text passes through humanize_text server side and a client side dash guard.
13. Tests: frontend component tests for blocks and streaming (MSW SSE), copy test extended, axe on assistant page.

COMMIT PLAN
- feat(llm): add model selection, client wrapper, limiter and quota handling
- feat(rag): add knowledge embedding, decision memory ingestion and hybrid search
- feat(agents): add tool layer with tenant scoped tests
- feat(agents): add verifier, safety nodes and humanize pass
- feat(agents): add langgraph orchestration, checkpointer and action cards
- feat(chat): add chat endpoints, sse streaming, threads and feedback
- feat(agents): add monday analyst, exception investigator and scenario planner workflows
- test(agents): add eval harness, fake llm suite and adversarial cases
- feat(ui): add assistant panel, blocks, explain entry points and nudges
- docs(context): record models, eval results, quota findings and handoff for prompt 8

VERIFICATION GATE
- Fake LLM suite green in CI mode; adversarial verifier tests green
- No endpoint exposes agent_steps (test)
- make lint, typecheck, test (backend and frontend), check_copy green
- If a key exists: live eval report generated, scenario planner run end to end on fmcg_a with a lowered budget, grounded answer with a source chip
- Manual: ask five questions in the UI (why is this line high, what changed this week, what if budget drops by 20 percent, which items expire soon, a dosing question that must be refused)

CONTEXT UPDATES
progress.md P7.01 to P7.15. memory.md: chosen models, quotas seen, eval results, decisions, gotchas, handoff. agents-spec.md amended with real state shapes and prompts as built.

STOP CONDITIONS
Never let a failing verifier fall through to showing the draft. If live calls are not possible, say so plainly and mark the live items unchecked in progress.md.

FINAL REPORT
Under 20 lines: capabilities working, eval numbers, quota behaviour, what is unverified, what Prompt 8 starts with.
```

---

# Prompt 8: Hardening, deployment and documentation

```
This is Prompt 8 of 8: hardening, performance, deployment files, accessibility, documentation and a final audit. After this the product is ready for you to push and deploy.

STEP 0. ORIENT
Read CLAUDE.md, context/memory.md, context/progress.md, context/README.md, then completely: security.md (including the PR checklist and threat model), deployment.md (all sections), testing-strategy.md, ui-design-system.md (anti-template checklist), ui-copywriting.md (enforcement), architecture.md (performance budgets and deferred items), seed-data-spec.md (CLI), api-spec.md. Run git status and git log --oneline -30; confirm every earlier group in progress.md is ticked or has a documented reason. Report in 3 to 6 lines, then continue.

GOAL
A reviewed, measured, documented project with working deployment files. Group P8 (P8.01 to P8.12).

TASKS
1. Security review: walk security.md and its PR checklist item by item against the code. For each item write pass or fix. Fix findings with tests. Specific checks: tenant isolation matrix on every route (automate: iterate the OpenAPI routes, call each with tenant B credentials against tenant A ids), refresh cookie flags, CORS, CSP and headers, rate limits, error messages that leak nothing, secrets scan of the working tree and git history (grep for key patterns, no tool installs needed), dependency audit (pip-audit, npm audit) with justified exceptions only, RLS and grants, upload and export filename safety, log redaction, SSE auth, prompt injection tests still green.
2. Performance: EXPLAIN ANALYZE the heavy queries (rollup, stock list, plan detail, insights) on the full seed, add or adjust indexes through a new migration, measure API resident memory idle and after an export against the 512 MB budget, measure light pipeline time per tenant, check the frontend bundle. Record numbers in memory.md Measurements.
3. Demo tools: complete python -m app.jobs.run simulate-week (advance the synthetic world by one week, then run the light profile), a guarded demo reset (CLI only, refuses when ENV=production unless an explicit flag is given), the flagged demo login endpoint and UI buttons (default off), SIMULATE_WEEKLY workflow step (default off).
4. Deployment files finalised and tested as far as possible without cloud access: render.yaml, backend image build, vercel.json, monday-job.yml, ci.yml, .env.example complete and matching config.py (add a test that every env var read in config.py appears in .env.example), scripts/db_dump.sh. Do a local production-mode run: docker compose with ENV=production style settings, Secure cookie behaviour behind a local reverse proxy if feasible, otherwise document what was not tested.
5. Accessibility pass on main screens: keyboard-only walkthrough of login, sale entry, plan review, assistant; focus order; labels; contrast of tokens; reduced motion. Fix issues. Keep axe tests at zero violations.
6. Cross browser and mobile: run the Playwright flows in Chromium and, if available, Firefox and WebKit; run plan and sale entry at 390 and 768 widths; fix overflow and touch target issues.
7. E2E suite green on the seeded stack; add any missing flow (assistant basics with the fake LLM server flag).
8. README.md (repo root): what it is, why, architecture diagram (text or mermaid, no dashes in text), setup and commands, demo accounts (emails only, password comes from env), a limitations section, honest metrics from the synthetic accuracy report and the agent eval report, clear statement that data is synthetic and results are not customer savings. Humanized, specific, not marketing fluff.
9. docs/DEMO.md: a 2 minute walkthrough script, screenshots list (generate screenshots with Playwright into docs/screenshots and commit the small ones), and a short list of resume bullet candidates that obey D-040 (method claims on synthetic data, no invented customer results).
10. Final copy audit: check_copy on the entire repo, a crawl of every route in the running app dumping visible text and scanning it, banned word scan, exclamation scan. Final anti-template review of every screen with screenshots; fix what looks generated.
11. Final consistency check of all context files against the code: table and column names, endpoint paths, env vars, make targets, scenario ids, job subcommands, versions. Fix specs or code. List the changes in memory.md.
12. Release checklist for the human: a short ordered list (Supabase project and pooler string, run migrations from your laptop, seed from your laptop or a one off Action, Render service, Vercel project and rewrite target, GitHub secrets, first Monday job dispatch, smoke test URLs) derived from deployment.md, with exact commands and what to verify at each step. Write it into docs/RELEASE.md.

COMMIT PLAN
- fix(security): address review findings and add automated tenant isolation matrix
- perf(db): add indexes from query analysis and record measurements
- feat(infra): complete demo tools and flagged demo login
- chore(infra): finalise deployment files and env parity test
- fix(ui): accessibility and responsive fixes
- test(ui): extend end to end coverage
- docs(docs): add readme, demo script and release checklist
- docs(context): record final audit, consistency fixes and closing handoff

VERIFICATION GATE (everything, from a clean checkout state)
- docker compose down -v, make up, make migrate, make seed, make job-monday, make test, make lint, make typecheck, make check-copy, npm run build, Playwright e2e: all green, outputs shown
- pip-audit and npm audit summaries
- Secrets scan clean
- git status clean, git log shows formal bundled commits, no remote configured, nothing pushed

CONTEXT UPDATES
progress.md P8.01 to P8.12 and the acceptance criteria list at its end (tick each with evidence or note why not). memory.md: final measurements, open questions for the human, closing handoff stating that the project is ready for the human to push.

STOP CONDITIONS
If a security finding needs a design change that touches earlier specs, make the change, update the specs, log it, and continue. Do not leave a known high severity issue open.

FINAL REPORT
Under 20 lines: security findings fixed, measurements versus budgets, anything not verified because it needs cloud accounts, and the exact list of things I (the human) must do next.
```

---

# Resume prompt (use when a session ran out of context midway)

```
Resume work on Backroom. Read CLAUDE.md, context/memory.md (especially the Session handoff), context/progress.md and context/README.md, then run git status and git log --oneline -20. Find the first unticked item in progress.md for the current prompt group, check whether any half-finished work exists in the working tree (uncommitted files, failing tests), and tell me in 3 to 6 lines where we are. If the working tree has uncommitted changes that belong together, finish the unit, run its tests, lint and check_copy, and commit it as one formal bundled commit. Then continue the remaining items of the current prompt group exactly as the group describes, following the same commit and context update rules. Never push. Stop after the group's gate passes and give the final report.
```

---

# Notes for you

- Paste the contents of the code block only, not the heading.
- If you rename the product, tell the first session once ("rename Backroom to X everywhere including context files") and let it do it in one commit before Prompt 1 continues.
- Prompt 3 uses web search for festival dates once. Prompt 7 needs your Gemini key. Prompt 8 needs nothing from the cloud, but its release checklist lists what you must do next.
- If a prompt's gate fails and the session cannot fix it, start a new session with the resume prompt and add one line saying what failed.
