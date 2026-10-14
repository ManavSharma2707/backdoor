# Architecture

Backroom is a modular monolith: one React app, one FastAPI app, one PostgreSQL database, one scheduled pipeline. Decision logic is numerical and auditable. The agent layer sits on top, read only, and can be switched off.

Source proposal: "Retail Inventory and Procurement Intelligence MVP Proposal" (October 2026). Where this file extends the proposal, this file wins.

---

## 1. Principles (non-negotiable)

1. **One output matters**: the Monday plan. Everything else exists to make it correct and understandable.
2. **The ledger is the truth**. Stock is derived from `inventory_movements`. Nothing edits history. Corrections are new records.
3. **Deterministic engine, honest forecasts**. Baselines first, chronological backtests, every forecast stored with its data cutoff and model version.
4. **Humans decide**. The system recommends, a person approves, edits or rejects. No auto-ordering. No clinical substitution.
5. **Show the gaps**. Missing price, lead time, expiry, stock count: surface it as a warning on the line. Never hide it, never invent it.
6. **LLMs explain, they do not calculate**. Every number in a chat answer comes from a tool result. Agents cannot write quantities.
7. **Synthetic data is labelled synthetic** in the UI, exports and docs. No claims of real savings.
8. **Tenant isolation everywhere**: JWT claim, repository filter, composite foreign keys, RLS deny-all on the public API.
9. **India first**: Rupee formatting, IST, Maharashtra festival calendar, GST slabs, monthly ration shopping patterns, monsoon and summer patterns.
10. **Small and dependable beats large and unfinished**.

## 2. System context

```
Browser (React, Vercel)
   | same-origin /api/*  (Vercel rewrite)          optional direct SSE
   v                                                     |
FastAPI on Render (free, 512 MB, 0.1 CPU) <--------------+
   |  SQLAlchemy / psycopg3 (Supabase session pooler)
   v
PostgreSQL on Supabase (free, 500 MB)  + pgvector + pg_trgm + citext
   ^
   |  same code, run as a script
GitHub Actions (cron, Monday 06:00 IST): `python -m app.jobs.run monday --profile full`
   - statistical forecasts, LightGBM, backtests, replenishment, report, Monday Analyst agent
   |
Gemini API (chat, agents, embeddings)  <- called from API and from the Actions job
```

Why the heavy job runs in GitHub Actions: Render free gives 0.1 CPU. LightGBM training and backtests would time out or crawl. Actions runners have 2 vCPU and 7 GB, no cold start, and reach Supabase through the IPv4 session pooler. The API only runs the **light** profile on demand (statistical methods, reuse of stored selections and events), plus dry-run scenarios that reuse stored forecasts.

## 3. Repo layout

```
backroom/
  CLAUDE.md
  context/*.md
  docker-compose.yml  Makefile  render.yaml  .env.example  .gitignore  .editorconfig
  .github/workflows/ci.yml  monday-job.yml
  scripts/check_copy.py  db_dump.sh
  backend/
    pyproject.toml  uv.lock  Dockerfile  start.sh  alembic.ini  openapi.json (generated)
    alembic/env.py  alembic/versions/
    app/
      main.py version.py            app factory, middleware, router mount, version string
      core/   config.py security.py db.py deps.py errors.py logging.py ratelimit.py
              audit.py idempotency.py pagination.py clock.py money.py timeutil.py repo.py
              messages.py middleware.py text.py   (built in Prompt 1: error codes and default
              messages, request id and security headers, humanize_text and the banned word list)
      models/ base.py reference.py tenancy.py catalogue.py suppliers.py sales.py
              purchasing.py inventory.py intelligence.py ops.py agents.py
      schemas/ common.py            Pydantic models per domain (error envelope, health)
      api/v1/ router.py auth.py settings.py catalogue.py suppliers.py sales.py purchasing.py
              inventory.py reports.py insights.py calendar.py jobs.py chat.py actions.py
              dashboard.py exports.py health.py
      services/ auth_service.py ledger.py sales_service.py purchasing_service.py
                inventory_service.py catalogue_service.py rollup.py dq_service.py
                report_service.py decision_service.py dashboard_service.py
                export/ pdf.py xlsx.py csv.py common.py
      engine/ types.py calendar.py features.py demand_class.py event_effects.py
              methods/ naive.py moving_average.py weekday.py ses.py croston.py lgbm.py
              backtest.py selection.py forecast.py inventory_state.py expiry.py
              replenishment.py budget.py risk.py deadstock.py dq.py report_builder.py
              pipeline.py scenario.py
      agents/ graph.py state.py llm.py quota.py guardrails.py verifier.py blocks.py
              nodes/  tools/  rag/  prompts/  evals/
      jobs/ run.py migrate.py reference_data.py monday.py rollup_job.py simulate_week.py
      assets/fonts/                 IBM Plex Sans and Mono TTF (for PDF)
    seed/ run.py generate.py sim.py demand.py pricing.py scenarios.py loader.py catalogs/*.yaml catalog/ corpus/ validate.py size_report.py realism.py checksum.py
    tests/ unit/ engine/ integration/ api/ seed/ agents/ conftest.py
  frontend/
    package.json  vite.config.ts  tsconfig*.json  eslint.config.js  vercel.json  index.html
    src/ main.tsx router.tsx  styles/index.css  copy/en.ts
         lib/ api.ts auth.ts format.ts sse.ts queryClient.ts utils.ts
         store/ auth.ts ui.ts
         components/ ui/ layout/ data/ charts/ feedback/ assistant/
         features/ auth overview plan products sales purchases stock insights settings assistant
         types/api.d.ts (generated)  hooks/  test/
```

## 4. Backend structure

**Layers**: `api` (HTTP only: parse, authorise, call service, shape response) -> `services` (business rules, transactions) -> `models` (SQLAlchemy). `engine` is pure and called by services and jobs. `agents` call services through read-only tools.

**Request lifecycle**: middleware assigns `request_id` -> security headers -> CORS -> rate limit -> route -> dependency `get_current_user` validates the access JWT and builds `TenantContext(tenant_id, user_id, role)` -> service call inside `with db.begin()` -> response model -> error handler converts exceptions to the standard envelope.

**Database access**: SQLAlchemy 2.0 sync sessions, psycopg 3, one session per request. `core/repo.py` provides `TenantRepo` which injects `tenant_id` into every query. Pool: `pool_size=5, max_overflow=2, pool_pre_ping=True, pool_recycle=1800`.

**Errors**: one envelope, see `api-spec.md`. Domain errors subclass `AppError(code, http_status, message)`. Never leak stack traces.

**Transactions**: each service method is one transaction (`core.db.transaction`, re-entrant, commit at the outermost level). Ledger writes (sale, return, receipt, adjustment, count) lock affected `stock_balances` rows with `SELECT ... FOR UPDATE` in primary key order to avoid deadlocks.

**Idempotency**: `POST /sales`, `/sales/{id}/returns`, `/purchase-orders/{id}/receipts`, `/receipts`, `/inventory/adjustments`, `/suppliers/{id}/returns`, `/jobs/*` accept `Idempotency-Key` (`core/idempotency.py`). Same key and same body returns the stored response. Same key and different body returns 422.

**Background work**: FastAPI `BackgroundTasks` for light jobs (report regenerate, agent actions). `job_runs` rows record status. Anything over about 60 seconds must be a script run in Actions.

**Config**: `pydantic-settings`, one `Settings` object, validated at start. Fail fast on missing secrets in production.

**Logging**: `structlog` JSON, fields `request_id, tenant_id, user_id, route, duration_ms`. No PII beyond ids. Never log tokens, passwords, API keys or full prompts.

## 5. Frontend structure

React 19 + TypeScript strict + Vite. Routing with React Router (data router). Server state with TanStack Query. Client state is small: auth (in memory) and UI (assistant panel, filters). Forms with React Hook Form + Zod. Tables with TanStack Table. Charts with Recharts. Styling with Tailwind v4 tokens and Radix primitives wrapped as our own components.

- `lib/api.ts`: fetch wrapper. Adds bearer token, on 401 calls `/auth/refresh` once (single-flight), retries the request, otherwise routes to login. Parses the error envelope into `ApiError`.
- Money and quantities arrive as strings. Format with `lib/format.ts` only. Do arithmetic on the server.
- Types come from `openapi-typescript` run against the FastAPI schema (`make openapi-types`).
- Every list screen reads filters from the URL query string so views are linkable.
- The assistant is a docked panel available on every screen and also a full page.

---

## 6. Features in detail

Each feature lists purpose, rules, data, endpoints, edge cases. Endpoint detail is in `api-spec.md`, tables in `database.md`.

### F01 Authentication and session
- Email and password login, argon2id hashes, short-lived access JWT (15 min, in memory), rotating refresh token in an httpOnly cookie (14 days) stored hashed server side.
- Reuse of a rotated refresh token revokes the whole token family and logs `auth.refresh_reuse`.
- Lockout after 5 failed attempts in 15 minutes (15 minute lock) plus per-IP rate limit.
- Endpoints: login, refresh, logout, logout-all, me, change-password. Registration exists behind `ALLOW_REGISTRATION` (default off). Optional `demo-login` behind `DEMO_LOGIN_ENABLED` (default off), only for tenants with `is_synthetic = true`.
- One owner login per tenant for now. `role` column exists (`owner`, `manager`, `staff`); only `owner` is used. Endpoints declare a minimum role through a dependency so staff roles can be added later without rewrites.
- Cold start: the login page pings `/health` on load. API client retries login and refresh once on timeout.
- Full detail: `security.md`.

### F02 Tenant and business settings
- Settings row per tenant (`business_settings`): weekly budget (optional), service level (default 0.95), review period (7), default lead time (3), near-expiry window (90), non-moving days (60), slow cover days (90), excess horizon (30), stale count days (30), shelf life fraction (0.6), priority weights, pack rounding mode, censor policy, agent switch.
- Changing a setting is audit logged. Settings take effect on the next report generation, never retroactively.
- `tenants.is_synthetic` drives the "demo data" label in the UI and exports.

### F03 Product catalogue
- Products with SKU (unique per tenant), name, brand, category (two-level tree), base unit (the sellable pack: pcs, pack, strip, bottle, tube, kg, litre), pack label, MRP, selling price, GST rate, batch tracking flag, shelf life days, schedule class flag (`H`, `H1`, flag only), minimum display stock, seasonal flag, launch date, active flag. Medical extras: generic name, strength, dosage form, manufacturer (descriptive only).
- Price changes create `product_prices` rows with effective dates. `products.selling_price` mirrors the current one.
- Product equivalents are retailer-defined links only. The system never proposes substitutes.
- Deactivate instead of delete. Products with history cannot be deleted.
- Search is trigram based on name, SKU, brand, generic name.

### F04 Suppliers and terms
- Supplier fields: payment terms, default lead time, delivery weekdays, minimum order value, expiry-return policy (accepts or not, window days), return window.
- `supplier_product_terms` are effective dated: purchase price, pack size, minimum order quantity, lead time, primary flag. Exactly one primary current term per product.
- Lead time resolution order: product term, supplier default, business default (flagged "assumed").
- Supplier scorecard (insights): delay rate, average delay days, fill rate, price drift, pack friction. Computed from POs and receipts.

### F05 Sales and returns
- A sale (bill) has lines. Each line has product, optional batch, quantity, unit price, discount, tax rate. Totals are computed server side.
- For batch tracked products the server allocates stock First Expired First Out (FEFO) across batches, splitting a line into one line per batch. The user may override the batch. A batch cannot go below zero.
- Creating a sale writes sale rows and one `sale` inventory movement per line in one transaction.
- Duplicate protection: `bill_no` unique per tenant, idempotency key, plus a soft warning if an identical basket was saved in the last 2 minutes.
- Void: only whole bills, with a reason. Writes reversing movements. Voided bills are excluded from demand.
- Returns: against a bill line, with quantity limit (sold minus already returned), reason and disposition: `restock` (back to usable stock), `damaged` or `expired` (not usable, written off). Each disposition has defined movements (see `database.md`).
- Seeded sales are `source = 'seed'`. Demo bills are not distinguishable in the UI except the demo label.

### F06 Purchasing and goods receipt
- Purchase order: draft, sent, partially received, received, cancelled, closed. Expected date comes from lead time and supplier delivery weekdays.
- POs can be created manually or from approved Monday plan lines (grouped by supplier, one draft PO per supplier).
- Goods receipt posts quantities, costs, and for batch tracked products batch number, expiry date and MRP. Posting creates batches, `receipt` movements, updates `stock_balances` (weighted average cost) and the PO line received quantity.
- Rules: receipt quantity cannot exceed the open PO quantity unless flagged as an exception with a note. A cancelled PO never counts as incoming. A PO past its expected date and not received is `overdue` and is excluded from confident incoming stock.
- Receipt without a PO is allowed only as an exception.

### F07 Inventory ledger, balances, batches, counts, adjustments, stockouts
- Every stock change is a row in `inventory_movements` with signed quantity, type, source reference, user and timestamp.
- `stock_balances` is a transactional cache (per product and per batch) updated in the same transaction. A reconciliation check compares it to the ledger sum and raises `BATCH_QTY_MISMATCH` if different.
- Movement types: `opening`, `receipt`, `sale`, `void_reversal`, `return_in`, `damage`, `expiry_writeoff`, `supplier_return`, `adjustment`, `count_correction`.
- Stock counts: draft with system quantity snapshot, counted quantity, variance. Posting creates `count_correction` movements. Last count date per product feeds the stale count warning.
- Adjustments: reason coded (damage, expiry write-off, theft or loss, found, correction, supplier return, other), always with a note when reason is `other`.
- Stockout intervals: the user can record that a product was out of stock between two dates. The rollup also infers intervals from the ledger (`source = inferred`). Recorded intervals are the only ones that are trusted as true unavailability for censoring beyond what the ledger shows.
- Expired batches are flagged `expired` by the daily rollup. Their remaining quantity is not sellable. The user is prompted to write them off.

### F08 Daily rollup and data checks
- `rollup` job builds `daily_product_stats` (units sold, returns, revenue, opening and closing stock, availability state, censored flag, promo flag) incrementally from the last rolled-up date.
- Availability states: `available`, `stocked_out_all_day`, `sold_out_during_day`, `not_launched`, `unknown`. Only `available` days are fully trusted demand. `sold_out_during_day` days are lower bounds.
- Data checks (`dq`) produce `data_quality_issues` with codes and severities (full list in `engine-spec.md`). They run at the start of the Monday pipeline and on demand from the dashboard.

### F09 Calendar and events
- Global `calendar_events` table: festivals, seasons and holidays with dates, before and after windows, expected supplier delay days, and a verified flag. Seeded from `india-calendar.md`.
- Owner can add or edit events and configure a manual effect for a category. Configured effects are labelled "assumed" in reports.
- A DQ check warns if no event is defined for the next 60 days.

### F10 Forecasting and backtests
- Product level daily demand forecast for a horizon of 28 days (7 days shown as the core horizon). Candidate methods: seasonal naive, moving average, weekday profile, SES with weekday seasonality, Croston SBA (intermittent), LightGBM global model (full profile only).
- Method selection per segment (category x demand class) by chronological backtest, with a parsimony rule against the moving average baseline.
- Event multipliers from learned effects apply only with evidence (see `engine-spec.md`).
- Stockout-censored days are excluded from training by default, never imputed silently.
- Each forecast run stores cutoff, model version, config and per-method backtest metrics (MAE, WAPE, bias, coverage).
- Prediction intervals come from backtest residual quantiles.

### F11 Replenishment and budget
- For each product: protection period (lead time plus review period plus festival delivery padding), demand over that period, usable on-hand after expiry loss, confirmed incoming, reserved, safety stock, raw requirement, MOQ and pack rounding, expiry cap, suggested quantity.
- Budget allocation uses a transparent priority score and greedy fill in whole packs. Unfunded demand and residual risk are stated plainly.
- Output is `recommendation_lines`, one per active product, each with reason codes, provenance tags (observed, calculated, assumed) and warnings.

### F12 Expiry, dead stock, excess
- Batch aware FEFO simulation gives expected expiry loss and exposure value (at purchase cost) per batch and per product.
- Slow moving, non-moving, excess definitions with configurable thresholds. A non-moving label is only assigned when the product was available, is not new, and not out of season. Otherwise the label is `unverified`.
- Medicine batches near expiry list batch id, quantity, expiry date, exposure value and operational options (sell first, return to supplier if policy allows, write off).

### F13 Monday job and report
- Pipeline: validate, rollup, refresh calendar and effects, backtest (full profile), forecast, inventory state, replenishment, budget, risk, expiry and dead stock, section building, persist, agent review, finish. Details in `engine-spec.md`.
- Schedule: Monday 06:00 IST via GitHub Actions. Data cutoff is Monday 00:00 IST. Idempotent per tenant and week through `job_runs`.
- Report snapshot stored as JSON in `weekly_reports.payload` plus normalised `recommendation_lines`, so the page loads fast and reproduces exactly.
- Regenerate creates a new version and marks the old one superseded.
- Layout in `report-spec.md`.

### F14 Decisions and purchase order drafts
- Per line: approve, edit quantity (with reason) or reject (with reason). Decisions are append only, the latest wins.
- Edit uses pack steps and shows spend and budget impact immediately.
- Bulk approve and reject. Approved totals shown against budget.
- "Create purchase orders" converts approved and edited lines into draft POs grouped by supplier. Lines with missing supplier or cost are blocked with a clear message.

### F15 Exports
- PDF (report), Excel (multi-sheet, formatted, formulas for totals), CSV (purchase list and full lines). Filters by supplier and section. File names `backroom_{tenant}_monday-plan_{YYYY-MM-DD}.{ext}`. Demo label on every export. Layout in `report-spec.md`.
- Exports are generated on demand from the stored snapshot so they always match the screen.

### F16 Dashboard and insights
- Overview: stock value, suggested spend, critical lines, stock not moving value, near expiry value, data warnings, needs-attention list, sales trend with festival bands, stock cover by category.
- Insights: sales and trends, fast and slow movers (ABC by revenue), forecast accuracy and bias, forecast versus actual, festival effects learned, supplier scorecard, expiry and waste.

### F17 Assistant and agents
- Read-only explainer with 24 capabilities, a goal-driven scenario planner, a Monday analyst, an exception investigator, data-quality and supplier prep agents.
- Details, tools, guardrails and evals in `agents-spec.md`. Feature flag `AGENTS_ENABLED`. The product works fully with it off.

### F18 Demo data and live demo mode
- `seed.run` creates four tenants with 78 weeks of history ending Sunday 2026-10-11, plus 8 weeks of retrospective weekly reports with synthetic decisions, plus the knowledge corpus.
- `simulate_week` extends the history by one week for synthetic tenants so the demo stays current. A weekly Action can run it before the Monday job (`SIMULATE_WEEKLY=true`, default off).
- Demo reset (`seed-reset`) is a script. In the UI, a reset button exists for synthetic tenants only, behind owner confirmation, and is disabled in production unless `ALLOW_DEMO_RESET=true`.

### F19 Operations and audit
- `job_runs` table with status, attempts, errors. `/jobs/runs` for the owner.
- `audit_logs` for auth events, setting changes, adjustments, counts, approvals, edits, report runs, exports, agent action confirmations.
- Health: `/health` (liveness, no DB), `/health/ready` (DB check).

---

## 7. Key flows

**Record a sale**: UI builds basket -> `POST /sales` with `Idempotency-Key` -> service validates products and stock -> FEFO allocation -> insert sale, lines, movements, update balances (row locks) -> response with bill total -> UI invalidates stock and dashboard queries.

**Monday pipeline** (per tenant): acquire advisory lock -> `job_runs` insert (skip if succeeded) -> DQ checks -> rollup -> events and effects -> backtest and selection (full) -> forecast run -> load inventory state -> replenishment lines -> budget allocation -> risk, expiry, dead stock -> build sections and snapshot -> persist all in one transaction -> optional agent review (separate transaction, failure does not fail the report) -> mark succeeded.

**Chat turn**: `POST /chat/threads/{id}/messages` -> SSE stream -> graph: router -> specialist loop with read-only tools -> verifier -> safety -> blocks -> `done`. Tenant and user come from the JWT, injected into graph state, never from the prompt.

## 8. Configuration and environment

Full variable table in `deployment.md`. Rules: all config via env, `.env.example` complete, production refuses to start with default secrets, feature flags: `ALLOW_REGISTRATION`, `DEMO_LOGIN_ENABLED`, `AGENTS_ENABLED`, `ALLOW_DEMO_RESET`, `SIMULATE_WEEKLY`.

## 9. Performance and size budgets

| Item | Budget |
|---|---|
| API p95 for list endpoints | under 400 ms warm (excluding cold start) |
| Light pipeline per tenant | under 60 s on Render free |
| Full pipeline per tenant (Actions) | under 8 min including LightGBM |
| API memory | under 400 MB resident |
| Database total | under 400 MB with all four tenants (limit 500 MB) |
| Report page payload | under 1.5 MB uncompressed |
| Chat first token | under 4 s warm |

## 10. Deferred, not in this build

Staff and manager roles and invites, email password reset, supplier ordering integrations, WhatsApp, OCR, imports from customer systems, multi-store, multilingual UI, offline mode, GST filing. The schema leaves room for roles and multi-store (`stores` is not created yet, add later with a nullable `store_id`).
