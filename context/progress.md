# Progress

Single checklist for the whole build. Tick items as soon as they are done and verified, add the date. Add new items when you discover work (give them the next free id in the group). Do not delete items.

Format: `- [x] P2.04 Description` becomes `- [x] P2.04 Description (2026-10-15)`.

**Status header (update every session)**
- Current prompt: Prompt 3 complete (seed data), Prompt 4 (intelligence engine and report) is next
- Last commit: the `docs(context)` commit that closes Prompt 3, after the `feat(seed)` commits. Nothing pushed
- Last updated: 2026-10-14 (Prompt 3 done: four tenants seeded at 359 MB, validation green, 110 seed tests in about 2 minutes)
- Blockers: none. The host system drive is nearly full (about 5 GB free), see `memory.md` section 6

---

## Prompt 1: Foundation and database

- [x] P1.01 Repo skeleton, folders per `architecture.md`, `.gitignore`, `.editorconfig`, `.env.example` (2026-10-13)
- [x] P1.02 `pyproject.toml` with uv, dependencies from `libraries.md`, ruff, mypy, pytest config (2026-10-13)
- [x] P1.03 Backend Dockerfile (multi stage, libgomp1), `start.sh`, `docker-compose.yml` (db, api, web), DB init script (test db, extensions) (2026-10-13)
- [x] P1.04 `core/config.py` (pydantic-settings, production strict checks), `core/logging.py` (structlog, redaction), `core/clock.py`, `core/money.py`, `core/timeutil.py`, `core/text.py` (humanize_text) (2026-10-13)
- [x] P1.05 `core/db.py` (engine, session, pool), `core/repo.py` (TenantRepo), `models/base.py` (naming convention, TenantMixin, composite FK helper) (2026-10-13)
- [x] P1.06 All SQLAlchemy models per `database.md` (reference, tenancy, catalogue, suppliers, sales, purchasing, inventory, intelligence, ops, agents) (2026-10-13)
- [x] P1.07 Alembic setup and migrations 0001 to 0010 (extensions, triggers, views, RLS, grants, HNSW and GIN indexes) (2026-10-13)
- [x] P1.08 Reference data seeding: tax rates and calendar events (`india-calendar.md`) as idempotent upsert (2026-10-13)
- [x] P1.09 FastAPI app factory, error envelope, request id middleware, security headers, CORS, health endpoints (2026-10-13)
- [x] P1.10 Makefile targets from `CLAUDE.md` (2026-10-13)
- [x] P1.11 `scripts/check_copy.py` and pre-commit config (2026-10-13)
- [x] P1.12 Test infrastructure: `conftest.py`, transaction rollback fixture, factories, two-tenant fixture (2026-10-13)
- [x] P1.13 Tests: migrations up, down, up. Composite FK cross-tenant rejection. CHECK constraints. Partial unique indexes. Audit log immutability. RLS deny test (2026-10-13)
- [x] P1.14 CI workflow `ci.yml` (backend, copy; frontend job stubbed until P5) (2026-10-13)
- [x] P1.15 Gate: `make up` works, `make migrate` clean, `make lint test` green, health endpoints respond (2026-10-13)
- [x] P1.16 Context updates (memory pinned versions, README index, progress) (2026-10-13)

## Prompt 2: Auth and transactional core

- [x] P2.01 Password hashing, policy, common password list, lockout fields (2026-10-14)
- [x] P2.02 JWT access tokens (claims, validation), refresh token rotation, reuse detection, grace window, cookie handling (2026-10-14)
- [x] P2.03 Auth endpoints (login, refresh, logout, logout-all, me, change-password), registration and demo-login behind flags (2026-10-14)
- [x] P2.04 Rate limiting (slowapi), audit logging service, `require_role` dependency, `TenantContext` (2026-10-14)
- [x] P2.05 Auth tests (rotation, reuse, lockout, timing path, cookie attributes, flags default off) (2026-10-14)
- [x] P2.06 Settings endpoints and validation (2026-10-14)
- [x] P2.07 Categories, products (with prices, search), equivalents, tax rates endpoints and services (2026-10-14)
- [x] P2.08 Suppliers and effective-dated terms (primary uniqueness, lead time resolution helper) (2026-10-14)
- [x] P2.09 Ledger service (movements, balances with row locks, weighted average cost, FEFO allocator) (2026-10-14)
- [x] P2.10 Sales service and endpoints (create with idempotency, FEFO split, totals, void, duplicate warning) (2026-10-14)
- [x] P2.11 Returns service (dispositions, movement pairs, quantity limits) (2026-10-14)
- [x] P2.12 Purchasing service (POs, state machine, receipts, batches, exception rules, overdue) (2026-10-14)
- [x] P2.13 Inventory endpoints (stock, batches, movements, adjustments, write off, counts, stockout intervals, reconcile) (2026-10-14)
- [x] P2.14 Idempotency dependency (`run_idempotent`) and table use (2026-10-14)
- [x] P2.15 Property tests for ledger invariants (see `testing-strategy.md` section 3, items 1 to 5) (2026-10-14)
- [x] P2.16 API tests: 401, two-tenant matrix for every route, error envelope, idempotency (2026-10-14)
- [x] P2.17 Gate: coverage targets (auth 90, ledger 90), OpenAPI generated, lint and types green (2026-10-14)
- [x] P2.18 Context updates (2026-10-14)

## Prompt 3: Seed data

- [x] P3.01 Catalogue YAML for fmcg_a (92), fmcg_b (118), med_a (150), med_b (152) with counts per category as in `seed-data-spec.md` (2026-10-14)
- [x] P3.02 Verify calendar dates marked `verify` using two sources, update `india-calendar.md` and the seed rows, log in memory (2026-10-14)
- [x] P3.03 Generator core: RNG, demand model (weekday, month-day, season, events, promotions, price effect, trend), true demand (2026-10-14)
- [x] P3.04 Simulation loop: receipts, stock-limited sales, bills, returns, adjustments, ordering policy, counts, stockouts, promotions, price changes (2026-10-14)
- [x] P3.05 Medical batch logic (batches, FEFO issue, expiry write-offs, supplier returns) (2026-10-14)
- [x] P3.06 Planted scenarios S01 to S21 with `scenarios.yaml` (2026-10-14)
- [x] P3.07 Bulk loader (COPY), balances rebuild, daily rollup run, `synthetic_true_demand` (2026-10-14)
- [x] P3.08 Users and settings creation (owner per tenant, password from env), budgets per scenario (2026-10-14)
- [x] P3.09 Knowledge corpus generator (supplier docs, product notes, app knowledge) and text-only ingestion (2026-10-14)
- [x] P3.10 `seed.validate`, `seed.size_report`, `--reset`, `--scale`, determinism checksum (2026-10-14)
- [x] P3.11 Seed tests at scale 0.1 and realism report (2026-10-14)
- [x] P3.12 Gate: full seed of all four tenants under 400 MB, validation green (2026-10-14)
- [x] P3.13 Context updates (record actual volumes and sizes) (2026-10-14)

## Prompt 4: Intelligence engine and report

- [x] P4.01 Rollup service (`daily_product_stats`) incremental and rebuildable (2026-10-14)
- [x] P4.02 DQ checks with all codes in `engine-spec.md` section 14 (2026-10-14)
- [x] P4.03 Demand classification (2026-10-14)
- [x] P4.04 Forecast methods (seasonal naive, moving average, weekday profile, SES weekday, Croston SBA, category prior) (2026-10-14)
- [x] P4.05 LightGBM global model (lazy import, caps, fallback) (2026-10-14)
- [x] P4.06 Event effect learning and gate (festival, season, promotion), medical stricter gate (2026-10-14)
- [x] P4.07 Backtest runner, selection per segment, confidence labels (2026-10-14)
- [x] P4.08 Inventory state, overdue PO handling, FEFO expiry simulation (2026-10-14)
- [x] P4.09 Replenishment (lead time resolution, safety stock, MOQ, pack, expiry cap, spend) (2026-10-14)
- [x] P4.10 Risk model and levels (2026-10-14)
- [x] P4.11 Budget allocation and budget view (2026-10-14)
- [x] P4.12 Stock status (non-moving, unverified, slow, new), excess, ABC (2026-10-14)
- [x] P4.13 Report builder (sections, reason templates, provenance, snapshot JSON) (2026-10-14)
- [x] P4.14 Pipeline orchestrator (light and full profiles, idempotency, locks, force, retention) and job entry points (`python -m app.jobs.run monday|backfill|migrate|simulate-week|reset-password`) (2026-10-14)
- [x] P4.15 Scenario dry run (Overrides) for later use by agents (2026-10-14)
- [x] P4.16 Report, decision, notes and PO draft endpoints, insights and dashboard endpoints (2026-10-14)
- [x] P4.17 Exports: PDF (ReportLab with Plex fonts), Excel (XlsxWriter), CSV (2026-10-14)
- [x] P4.18 Backfill of 8 weekly plans with synthetic decisions (2026-10-14)
- [x] P4.19 Tests: engine properties (see `testing-strategy.md` 3.6 to 3.14), scenario tests S01 to S21, golden pipeline output, export tests (2026-10-14)
- [x] P4.20 Synthetic accuracy report (`synthetic_accuracy.md`) with honest findings (2026-10-14)
- [x] P4.21 `monday-job.yml` workflow (2026-10-14)
- [x] P4.22 Gate: full pipeline for all tenants within time budgets, coverage targets, lint and types green (2026-10-14)
- [x] P4.23 Context updates (thresholds, backtest results, timings) (2026-10-14)
- [x] P4.24 Replace `seed/rollup_sql.py` (the SQL fallback written in Prompt 3) with the rollup service of P4.01, and make `seed.run` call the service (2026-10-14)
- [x] P4.25 Check the planted budgets (S08 at 70 percent, S09 at 105 percent of need) against the engine's unconstrained need and adjust `accounts.weekly_budget` if the ratios differ (2026-10-14)
- [x] P4.26 Add the backfill documents to the corpus (`decision_memory`, `report_narrative`) when the eight retrospective plans exist, and keep the database under 400 MB (about 41 MB of headroom after the seed) (2026-10-14)

## Prompt 5: Frontend foundation and core screens

- [ ] P5.01 Vite React TypeScript project, Tailwind v4 tokens from `ui-design-system.md`, fonts, ESLint, Prettier, Vitest, MSW
- [ ] P5.02 `lib/api.ts` (refresh single flight, error envelope), `lib/auth`, auth store, route guards, generated API types script
- [ ] P5.03 `lib/format.ts` (money, quantity, dates, compact INR) with tests, `copy/en.ts` skeleton
- [ ] P5.04 UI primitives (button, inputs, select, combobox, date picker, tabs, table, badge, dialog, drawer, tooltip, banner, empty state, skeleton, toast, pack stepper, command palette) and `/_ui` gallery
- [ ] P5.05 App shell (sidebar, top bar, demo strip, responsive behaviour)
- [ ] P5.06 Login screen with cold start handling and optional demo buttons
- [ ] P5.07 Overview screen (except assistant nudge)
- [ ] P5.08 Products list, add and edit, detail with tabs
- [ ] P5.09 Sales list, fast entry screen, bill detail, return and void
- [ ] P5.10 Purchases list, new order, detail, receipt form
- [ ] P5.11 Stock screens (levels, batches and expiry, movements, counts, out-of-stock history, adjustment dialog)
- [ ] P5.12 Settings screens (planning, calendar, account, about)
- [ ] P5.13 Component tests, copy test, axe tests, `vercel.json`, CI frontend job enabled
- [ ] P5.14 Gate: lint, types, tests, build green, anti-template review notes in memory
- [ ] P5.15 Context updates

## Prompt 6: Monday plan, insights and exports UI

- [ ] P6.01 Plan screen shell: header, week switcher, status, creating state, summary block, festival note
- [ ] P6.02 Buy tab with filters, URL sync, expand rows, provenance tags, bulk actions
- [ ] P6.03 Decisions: approve, edit with pack stepper and reasons, reject, optimistic updates, sticky footer
- [ ] P6.04 Do not buy, Watch, Reduce exposure (with batch table and write off) tabs
- [ ] P6.05 Festival and season tab with configured effect dialog
- [ ] P6.06 Budget tab and Data notes tab
- [ ] P6.07 Create purchase orders flow and blocked line handling
- [ ] P6.08 Downloads (PDF, Excel, CSV) via authenticated fetch, naming
- [ ] P6.09 Insights screens (all six tabs) with charts per design system
- [ ] P6.10 Charts with festival bands, Explain buttons wired to an assistant stub
- [ ] P6.11 Component tests for plan flows, e2e Playwright for login, plan decisions, export
- [ ] P6.12 Gate and context updates

## Prompt 7: RAG, agents and assistant

- [ ] P7.01 Pick current Gemini models via model listing, record in memory
- [ ] P7.02 LLM client wrapper, limiter, quota handling, message text helper
- [ ] P7.03 Knowledge ingestion with embeddings, live decision memory ingestion, narratives
- [ ] P7.04 RAG search (hybrid, RRF, tenant filter)
- [ ] P7.05 Tool layer (all tools in `agents-spec.md`) with tests per tool and two-tenant scoping
- [ ] P7.06 Verifier, humanize_text integration, safety nodes
- [ ] P7.07 LangGraph graph, state, router, specialists, responder, repair and fallback, caps
- [ ] P7.08 Postgres checkpointer, interrupt and resume for action cards, agent actions confirm endpoint
- [ ] P7.09 Chat endpoints, SSE streaming, threads, messages, feedback, pins, nudges
- [ ] P7.10 Workflows: Monday Analyst, exception investigator, goal-driven scenario planner (core), data-quality and supplier prep (polish)
- [ ] P7.11 Agent trace tables written, never exposed
- [ ] P7.12 Eval harness: cases, fake LLM suite, live suite, report
- [ ] P7.13 Frontend: assistant panel and page, blocks, source chips, action cards, follow-ups, starters, Explain entry points, nudges, tour, UI actions whitelist
- [ ] P7.14 Fallback behaviour when quota is exhausted or agents are disabled
- [ ] P7.15 Gate: fake LLM suite green, verifier adversarial tests green, dash check green, context updates

## Prompt 8: Hardening, deployment and documentation

- [ ] P8.01 Security review against `security.md` and the PR checklist, fix findings
- [ ] P8.02 Performance pass: EXPLAIN on heavy queries, indexes, memory check under budget
- [ ] P8.03 Demo tools: simulate week, demo reset (guarded), demo login (flagged)
- [ ] P8.04 Deployment files finalised: `render.yaml`, `vercel.json`, workflows, `.env.example`, `scripts/db_dump.sh`
- [ ] P8.05 Accessibility pass on main screens
- [ ] P8.06 Cross-browser and mobile pass on plan and sale entry
- [ ] P8.07 E2E suite green on the seeded stack
- [ ] P8.08 README: overview, architecture diagram, setup, demo accounts, limitations, honest metrics (backtest and agent eval summaries)
- [ ] P8.09 Demo script and screenshots list for the resume and a 2 minute walkthrough outline
- [ ] P8.10 Final copy audit (dashes, banned words), anti-template review of all screens
- [ ] P8.11 Final consistency check of all context files against the code
- [ ] P8.12 Release checklist handed to the human (`deployment.md` section 8)

---

## Acceptance criteria (from the proposal, restated)

- [ ] A seeded business can create sales and purchases, update stock, and generate the Monday report
- [ ] Report lines reconcile with the inventory ledger and declared supplier constraints
- [ ] All planted scenarios produce the expected warnings or recommendations in automated tests
- [ ] Forecasts are backtested against simple baselines and results recorded honestly
- [ ] No unresolved high severity access control, data integrity or duplicate job defects
- [ ] A reviewer can start from a clean database, load all four demo tenants, record a few new transactions, run the job, and obtain a consistent Monday report that explains itself and traces to its data cutoff
