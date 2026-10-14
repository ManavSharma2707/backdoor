# Memory

Persistent memory for every Claude Code session on this repo. Read it at the start of every session. Update it when you decide something, learn something, or end a session.

Sections: 1 Locked decisions, 2 Default parameters, 3 Open questions, 4 Decision log (append only), 5 Pinned versions, 6 Known issues and gotchas, 7 Measurements, 8 Session handoff.

---

## 1. Locked decisions (from planning, October 2026)

Change one only with a new log entry in section 4 that references its id.

| Id | Decision |
|---|---|
| D-001 | Working name **Backroom**. Tagline "Your buying plan, every Monday." The user may rename |
| D-002 | Stack: React 19 + TypeScript + Vite (Vercel), FastAPI + Python 3.12 (Render, Docker), PostgreSQL (Supabase, pgvector), pandas, scikit-learn, LightGBM, Docker for local and API image. The user wrote "uh, Render for backend, Vercel for front end, Supabase for DB" |
| D-003 | Package managers: uv (Python), npm (Node 22 LTS) |
| D-004 | SQLAlchemy 2.0 sync, psycopg 3, Alembic. Sync endpoints |
| D-005 | Four synthetic tenants, all Maharashtra, two FMCG (92 and 118 SKUs) and two medical (150 and 152 SKUs). **No location is mentioned in the UI, names or data.** Festival calendar is Maharashtra flavoured |
| D-006 | One owner login per tenant. Staff and manager roles are deferred, the `role` column and `require_role` dependency exist |
| D-007 | Auth: JWT access token 15 min in memory, rotating refresh token in httpOnly cookie 14 days (hashed in DB, reuse detection), argon2id, lockout, rate limits |
| D-008 | Cookie strategy: Vercel rewrite proxies `/api/*` to Render so the cookie is first party. Chat SSE may go direct to Render with bearer token if the rewrite buffers |
| D-009 | Render free is 0.1 CPU and 512 MB, so the full Monday pipeline (backtests, LightGBM, analyst agent) runs in a GitHub Actions job against Supabase. API runs only the light profile |
| D-010 | Forecast ladder: seasonal naive, moving average, weekday profile, SES with weekday seasonality, Croston SBA, LightGBM global model. Selected per segment (category x demand class) by chronological backtest with a parsimony rule against moving average |
| D-011 | Event effects are learned per tenant and category, applied only with evidence (gate in `engine-spec.md` 7.2). Medical festival effects need a stricter gate. No blanket festival uplift |
| D-012 | Stockout-censored days are excluded from training by default. No silent imputation. Warnings and confidence downgrade instead |
| D-013 | Exports: PDF (ReportLab, IBM Plex TTF for the Rupee sign), Excel (XlsxWriter, formulas with cached values), CSV (UTF-8 with BOM) |
| D-014 | Agent layer: LangGraph + langchain-google-genai (Gemini) + pgvector RAG. Read only, tool grounded, verifier, human confirm for any action. Agent steps are stored but never shown to users. Only friendly status lines are streamed |
| D-015 | Observability via own tables (`agent_runs`, `agent_steps`). No LangSmith |
| D-016 | Chatbot feature tiers per `agents-spec.md` section 1. Approved workflows: Monday Analyst, exception investigator, goal-driven scenario planner. Data-quality and supplier prep are polish |
| D-017 | Money and quantities are strings in JSON. Frontend formats only |
| D-018 | Light theme only for the MVP |
| D-019 | Fonts: IBM Plex Sans and Mono, self hosted |
| D-020 | No em dashes or en dashes anywhere, including UI, exports, assistant output, seed text and context files. Enforced by `check_copy.py` and `humanize_text` |
| D-021 | Git: commit only, never push. Work on `main`. Conventional Commits with bundled, formal commits. No co-author trailers or tool signatures in commit messages |
| D-022 | Tenant isolation: JWT claim, repository filter, composite foreign keys, RLS deny-all with revoked grants |
| D-023 | `text` plus `CHECK` instead of native enum types |
| D-024 | UUID primary keys, bigint identity for sale_lines, inventory_movements, forecast_values, audit_logs, agent_steps |
| D-025 | History window 2025-04-14 to 2026-10-11 (78 weeks). Opening balances 2025-04-13. First plan as_of 2026-10-12 |
| D-026 | Demo owner password from env `DEMO_OWNER_PASSWORD` (12+ chars). Never stored in the repo |
| D-027 | Embeddings 768 dimensions, L2 normalised, `vector(768)`, HNSW cosine |
| D-028 | `ALLOW_REGISTRATION` and `DEMO_LOGIN_ENABLED` default off. Demo login works for synthetic tenants only |
| D-029 | `simulate_week` keeps the demo current, optional (`SIMULATE_WEEKLY`) |
| D-030 | Password reset by email is deferred. Owner reset is a CLI script |
| D-031 | Free Gemini key receives synthetic data only |
| D-032 | Gemini model names are chosen at runtime in Prompt 7 by listing models. Never hard coded |
| D-033 | Plan week starts Monday, data cutoff Monday 00:00 IST, scheduled 06:00 IST via GitHub Actions cron `30 0 * * 1` UTC |
| D-034 | Pack rounding default `up` (as in the proposal example). `nearest_safe` optional |
| D-035 | Service level 0.95, review period 7 days, default lead time 3 days |
| D-036 | Budget priority weights: risk 0.45, value 0.30, confidence 0.15, excess penalty 0.10 |
| D-037 | Festival dates flagged unverified until checked against two sources (Prompt 3) |
| D-038 | Supabase is plain Postgres. No Supabase Auth, client libraries or PostgREST |
| D-039 | English only |
| D-040 | Resume honesty: synthetic results are never described as real customer savings. Claims are about the method (backtests against baselines on simulated data with hidden ground truth) |
| D-041 | Product names are fictional brands. Medicines use real generic names, no dosing or clinical data, schedule flag only |
| D-042 | GST structure: 0, 5, 18, 40 percent (effective 22 Sep 2025), representative mapping only, not tax advice |

## 2. Default parameters (live in `engine/constants.py` and `business_settings`)

| Parameter | Default |
|---|---|
| Forecast horizon | 28 days (7 core) |
| Backtest origins | 12 weekly (4 for LightGBM) |
| Parsimony threshold | 3 percent vs moving average |
| Confidence thresholds | high: coverage 0.80, WAPE 0.35. medium: coverage 0.60, WAPE 0.60 |
| Risk levels | critical p >= 0.60, high 0.30, medium 0.10 |
| Event gate | shift >= 0.15, consistency >= 0.60, products >= 3. Medical festivals: n >= 2 and consistency >= 0.75 |
| Shrinkage | `n / (n + 0.5)`, clip 0.5 to 3.0 |
| Near expiry window | 90 days (settings) |
| Non-moving window | 60 days, availability share >= 0.70 |
| Slow cover | 90 days |
| Excess horizon | 30 days |
| Shelf life fraction held | 0.60, cap 120 days |
| Stale count | 30 days (A class) |
| Login lockout | 5 failures, 15 minutes |
| Access token | 15 minutes |
| Refresh token | 14 days |
| Chat limits | 20 per minute, 200 per day per user |
| Agent caps | chat 8 LLM steps, 10 tool calls, 45 s. workflows 14 steps, 120 s |

## 3. Open questions (ask the user only if blocking)

1. Final product name (default: Backroom).
2. Enable `DEMO_LOGIN_ENABLED` on the public demo? (default: off until the human decides).
3. Enable `SIMULATE_WEEKLY` so the demo stays fresh? (default: off).
4. Email domain for demo owners is `backroom-demo.com` (no mail is ever sent). Change if the user prefers another.
5. Confirm festival dates marked "verify" (Prompt 3 does this and logs the result).

## 4. Decision log (append only)

Template:

```
### D-0xx (YYYY-MM-DD) Title
Context: what forced the decision
Choice: what we chose
Alternatives: what we rejected and why
Consequence: what this changes, files touched
```

### D-043 (2026-10-13) Composite aware constraint naming
Context: nearly every tenant scoped constraint starts with `tenant_id`, so the naming convention in `libraries.md` (`column_0_name`) produced duplicate names, and the two foreign keys of `product_equivalents` to `products` would have collided.
Choice: `ix`, `uq` and `fk` patterns use `column_0_N_name` (all columns joined). Every `Index` and `CheckConstraint` has an explicit name. SQLAlchemy shortens names over 63 characters with a hash.
Alternatives: hand naming every constraint (noisy, easy to forget).
Consequence: `models/base.py`, `database.md` section 1 and `libraries.md` amended. Spec change.

### D-044 (2026-10-13) `product_batches` is created in migration 0003
Context: `sale_lines`, `sale_return_lines` and `receipt_lines` hold composite foreign keys to `product_batches`, but `database.md` created it in `0006`, after those tables.
Choice: create `product_batches` in `0003_catalogue_suppliers`. The other `0006` tables are unchanged.
Alternatives: add the foreign keys later with `ALTER TABLE` (more code, a window with no integrity).
Consequence: `database.md` section 7 amended. Spec change.

### D-045 (2026-10-13) Health endpoints and one extra error code
Context: `api-spec.md` lists `/health` and `/health/ready` without a prefix, while Render, the Dockerfile and `deployment.md` use `/api/v1/health`. Starlette also answers wrong methods with 405, which had no code.
Choice: serve both at `/api/v1/health*` (documented) and as undocumented root aliases. Readiness checks the database and that `alembic_version` equals the newest revision on disk, and answers 503 with a small status body (not the error envelope) so uptime tools can read it. Add `METHOD_NOT_ALLOWED` 405 to the error codes.
Alternatives: root only (breaks the Render health path), envelope for 503 (harder for monitors).
Consequence: `api-spec.md` sections 1 and 10 amended. Spec change.

### D-046 (2026-10-13) Which foreign keys are not composite
Context: "every intra-tenant foreign key is composite" cannot hold where `tenant_id` is nullable or the parent does not exist yet.
Choice: plain keys only to `tenants`, `users`, `model_versions`, `tax_rates` and `knowledge_documents` (nullable tenant). Soft uuid columns without a key: `purchase_orders.recommendation_run_id`, `purchase_order_lines.recommendation_line_id`, `data_quality_issues.run_id`, `chat_messages.agent_run_id`. `audit_logs` has no keys at all so it survives demo resets. Added `UNIQUE (tenant_id, id)` to `refresh_tokens`, `inventory_movements`, `promotions` and `chat_threads` so `replaced_by_id`, `reverses_movement_id`, `stock_adjustments.movement_id`, `sale_return_lines.sale_line_id` and `agent_runs.thread_id` are composite. A structural test enforces the rule.
Alternatives: leave those columns unconstrained.
Consequence: `database.md` section 10 added. Spec change.

### D-047 (2026-10-13) Reference data semantics
Context: `india-calendar.md` marks festival dates `verify` and seasons `seasonal`; the prompt says unverified dates are `is_verified = false`.
Choice: festivals `false`, seasons `true` (a convention, not a moon dependent date), 2027 rows `false` with an "approximate" note. The upsert (`app/jobs/reference_data.py`, keyed by slug) never turns a verified row back to unverified, never changes `is_active`, and skips rows whose `source_note` is `owner`. Includes `summer-2025`, which the calendar mentions for completeness. 28 events and 4 GST slabs.
Alternatives: overwrite everything on each deploy (would undo the Prompt 3 verification).
Consequence: Prompt 3 flips `is_verified` in the code table, not only in the database.

### D-048 (2026-10-13) Expiry days use the IST date
Context: `v_batch_stock` used `CURRENT_DATE`, which is the server (UTC) date.
Choice: `(now() AT TIME ZONE 'Asia/Kolkata')::date`, so batches expire at IST midnight.
Consequence: `database.md` section 10 notes it. Spec change.

### D-049 (2026-10-13) CORS sends no credentials header
Context: `security.md` allows credentials only for refresh and logout. The cookie strategy (D-008) is same origin through the Vercel rewrite, so no cross-origin credentialed request exists, and Starlette's CORS middleware is global.
Choice: `allow_credentials=False`, explicit methods and headers, exposed headers `X-Request-ID`, `Idempotent-Replay`, `Retry-After`.
Alternatives: a per-route CORS layer (complexity with no user).
Consequence: if the chat stream goes direct to Render (D-008) it uses the bearer token, which needs no credentials. `api-spec.md` amended.

### D-050 (2026-10-13) Tooling layout
Context: the repo sits in OneDrive on Windows; a `.venv` inside it fails on file locks; compose bind mounts `./backend` over `/app`.
Choice: `[tool.uv] package = false` (no editable install, code imported from the working directory), docker venv at `/opt/venv`, uv image pinned to 0.13.0, host venv kept outside OneDrive through `UV_PROJECT_ENVIRONMENT`. Lint, types and tests run on the host, the stack runs in Docker. Pre-commit hooks run inside `backend/`.
Alternatives: run everything in containers (slow feedback on Windows), a venv in the repo.
Consequence: `libraries.md`, `deployment.md` amended. Spec change.

### D-051 (2026-10-13) Local default secrets and production checks
Context: the app must start on a clean checkout, but production must never run with a default secret.
Choice: `JWT_SECRET` and `JOB_TOKEN` default to long `dev-only-...` strings. In production the process refuses to start (`ConfigError`, all problems listed together) if a secret is under 32 characters or starts with `replace-with`, `change-me`, `dev-only` or `example`, if `COOKIE_SECURE` is false, `CORS_ORIGINS` is empty or `*`, or `DATABASE_URL` is the local default.
Consequence: `.env.example` uses the `replace-with` placeholders.

### D-052 (2026-10-13) Test database rules
Choice: the test database name must end in `_test` (the fixture exits otherwise), the public schema is dropped and rebuilt from the real migrations once per session, and tests that run migrations use a throwaway database. Source files write the long dash characters as `\u2014` and `\u2013` escapes because `check_copy.py` scans for the literal characters.
Consequence: `testing-strategy.md` amended.

### D-053 (2026-10-13) Dependency versions are newer than the planning notes
Context: `uv lock` on 2026-10-13 resolved SQLAlchemy 2.1.4, FastAPI 0.143, Pydantic 2.14, pandas 3.0.6, LangGraph 1.2.15, Alembic 1.20 and ruff 0.17. The suite passes on all of them.
Choice: keep the resolved versions (table in section 5). `libraries.md` says "SQLAlchemy 2.0" for the API style; 2.1 is compatible with every call used.

### D-054 (2026-10-13) Password minimum is 12 characters
Context: `security.md` said 10, the Prompt 2 brief says 12.
Choice: 12 (maximum 128). The common password list is matched after lowercasing, letter swaps and trimming digits and symbols from both ends, and repeated blocks are refused. The list is a curated file of about 575 entries because most of the "top 1,000" are under 12 characters and already fail the length rule.
Alternatives: keep 10 (weaker), a full 100k breach list (size, and no source we can vouch for).
Consequence: `security.md`, `core/security.py`, `app/assets/common_passwords.txt`. Spec change.

### D-055 (2026-10-13) Migration 0011: `last_failed_login_at` and nullable `counted_qty`
Context: "5 failures within 15 minutes" needs the time of the last failure, and a draft stock count needs a way to say "not counted yet".
Choice: `users.last_failed_login_at timestamptz null`, and `stock_count_lines.counted_qty` nullable (the generated `variance` is then NULL). Posting a count only touches counted lines.
Alternatives: store failure times in a new table (more rows for no gain), default `counted_qty` to `system_qty` (cannot tell counted from untouched).
Consequence: `database.md` amended, models updated. Spec change.

### D-056 (2026-10-13) Access token times are checked against our clock
Context: PyJWT validates `exp`, `nbf` and `iat` with the system clock, which tests cannot move and `CLAUDE.md` forbids reading directly.
Choice: signature, algorithm (HS256 only), issuer, audience and presence of all nine claims are checked by PyJWT, the three time claims by `core/security.py` against `now_utc()` with a 10 second leeway. `get_current_user` also loads the user and tenant, so a deactivated account is refused at once, and the database role (not the token role) is used for `require_role`.
Consequence: `core/security.py`, `core/deps.py`.

### D-057 (2026-10-13) Refresh rotation details
Context: `security.md` asks for a 10 second grace window that returns 401 without revoking.
Choice: the grace branch returns 401 and leaves the cookie alone (the browser already holds the winner's newer cookie). Any other presentation of a rotated or revoked token revokes the family and clears the cookie. Rotation locks the token row (`FOR UPDATE`), so two simultaneous refreshes are serialised and exactly one wins. Logout revokes the whole family. Change password keeps the family of the refresh cookie sent with the request and revokes the rest (all of them when no cookie is sent).
Consequence: `services/auth_service.py`.

### D-058 (2026-10-13) Rate limiting design
Context: slowapi key functions only see the request, but login must be limited per email, and signed in users have a general limit.
Choice: slowapi decorators for per IP limits (login, refresh, register, demo login), the `limits` library directly (`KeyedLimits`) for per email and per user limits. Limit strings come from settings (`RATE_LIMIT_*`), `RATE_LIMIT_ENABLED=false` switches everything off (tests). 429 uses the error envelope with `Retry-After`. In memory, one instance.
Consequence: `core/ratelimit.py`, `Settings`.

### D-059 (2026-10-13) Catalogue and settings rules
Context: `database.md` and `api-spec.md` leave several product rules open.
Choice: selling price may not exceed MRP (Legal Metrology). Medicine fields (generic name, strength, form, manufacturer, schedule flag) are accepted only for medical tenants. SKU and barcode are unique per tenant (barcode in the service, SKU also in the database). Batch tracking cannot be changed once a product has any movement. A price change closes the open `product_prices` row (`effective_to` the day before) and opens a new one, and a second change on the same day edits that day's row. References to a foreign category, tax rate or product in a body answer 404 with the field named. Categories have two levels. Product list `status` is `active` (default), `inactive` or `all`. Equivalents are deleted by link id (`DELETE /products/{id}/equivalents/{link_id}`). `GET /products` fills `days_of_cover` and `plan_status` with null until a plan exists. Settings ranges: service level 0.50 to 0.999, review 1 to 28, lead time 0 to 60, near expiry 7 to 365, non moving 14 to 365, slow cover 14 to 730, excess horizon 7 to 180, forecast horizon 14 to 56, backtest origins 4 to 26, stale count 7 to 180, shelf life fraction 0.10 to 1.00, weights add up to 1.
Consequence: `api-spec.md` amended. Spec change.

### D-060 (2026-10-13) Supplier term semantics
Context: `api-spec.md` says a new primary term end-dates the previous one, and the schema only enforces one open primary term per product.
Choice: terms for the same supplier and product, and primary terms for one product (any supplier), may not share a day. The one allowed overlap is the normal price change: a new open ended term closes an earlier open ended one on the day before it starts. Anything else is a 409. A started term's price and start date cannot be edited (past prices are history), other fields and `effective_to` can. Lead time resolution (`app/engine/lead_time.py`) is term, supplier default, business default (default 3), and 0 days is a real value. Expected delivery is the order date plus lead time moved to the next supplier delivery weekday. `GET /suppliers/{id}/scorecard` moves to Prompt 4 with the insights endpoints.
Consequence: `app/engine/lead_time.py`, `app/engine/term_rules.py`, `services/supplier_service.py`. `api-spec.md` amended.

### D-061 (2026-10-14) Sales, returns, voids and idempotency rules
Context: the specs leave GST handling, expiry edge cases, void with returns and replay details open.
Choice: prices include GST, so `tax_total` is the tax contained in the lines (line total * rate / (100 + rate), per line, rounded to paise) and `total = subtotal - discount_total = sum of line totals`. The expiry date is the first day a batch cannot be sold (`expiry_date > business date`). A unit price may not exceed MRP. A line discount is split across the batch parts of a split line by the largest remainder method, so parts add up to the discount. Bill creation takes a per tenant advisory lock (bill numbers `B{YYMM}-{seq:05d}`, returns `R{YYMM}-{seq:04d}`, same format as the seed) and then locks all balance rows of the products on the bill. A duplicate basket (same products and quantities, same total, within 2 minutes, completed) saves with a `POSSIBLE_DUPLICATE` warning, never a refusal. A bill with returns cannot be voided and a void bill cannot take returns. Returns restock to the sold batch; damaged and expired returns post `return_in` then `damage` or `expiry_writeoff`. Refunds are cumulative (refund for everything returned so far minus what was refunded) so part returns add up to the line total. Idempotency: table `idempotency_keys`, key unique per tenant and operation scope, request hash over a canonical body (numbers by value, so `1` equals `1.000`), TTL 48 hours (`IDEMPOTENCY_TTL_HOURS`), stored response in the same transaction as the work, per key advisory lock, refusals are not stored. After expiry a key can be reused, so `sales.idempotency_key` is left null when a sale already holds that key.
Consequence: `engine/ledger_rules.py`, `engine/sales_math.py`, `services/ledger.py`, `services/sales_service.py`, `core/idempotency.py`. `api-spec.md` amended.

## 5. Pinned versions

Exact versions are in `backend/uv.lock`. Recorded on 2026-10-13 from the resolved lock file (`D-053`).

| Package | Version | Note |
|---|---|---|
| python | 3.12.15 | Docker image python:3.12-slim, host uv python |
| uv | 0.13.0 | Docker image pinned. Host 0.13.0 |
| node | 22 (image node:22-alpine) | Host 22.13.1. Frontend arrives in Prompt 5 |
| postgres (pgvector/pgvector:pg16) | 16.15, pgvector 0.8.7 | citext 1.6, pg_trgm 1.6, pgcrypto 1.3 |
| fastapi | 0.143.0 | starlette 1.8.0, uvicorn 0.54.0 |
| sqlalchemy | 2.1.4 |  |
| psycopg | 3.3.6 | psycopg-binary 3.3.6, psycopg-pool 3.3.3 |
| alembic | 1.20.0 |  |
| pydantic | 2.14.1 | pydantic-settings 2.15.0 |
| pyjwt | 2.15.1 | not used yet |
| argon2-cffi | 25.1.0 | not used yet |
| pandas | 3.0.6 |  |
| numpy | 2.5.4 |  |
| scikit-learn | 1.9.1 |  |
| lightgbm | 4.7.0 |  |
| reportlab | 5.0.1 |  |
| xlsxwriter | 3.2.9 |  |
| langgraph | 1.2.15 | langgraph-checkpoint-postgres 3.1.3 |
| langchain-core | 1.6.10 |  |
| langchain-google-genai | 4.4.1 |  |
| google-genai | 2.30.0 |  |
| pgvector (python) | 0.5.1 |  |
| structlog | 26.1.0 |  |
| slowapi | 0.1.10 | not used yet |
| sse-starlette | 3.5.0 | not used yet |
| tenacity | 9.1.4 | not used yet |
| cachetools | 7.2.1 | not used yet |
| email-validator | 2.3.0 | not used yet |
| faker, pyyaml | 40.43.0, 6.0.3 | seed, Prompt 3 |
| pytest, pytest-cov, hypothesis | 9.1.1, 7.1.0, 6.169.0 |  |
| httpx, openpyxl, pypdf | 0.28.1, 3.1.5, 6.20.1 |  |
| ruff, mypy | 0.17.0, 2.4.0 |  |
| pre-commit, pip-audit | 4.7.0, 2.10.1 | pip-audit found no known vulnerabilities on 2026-10-13 |
| react, vite, tailwindcss, @tanstack/react-query, recharts, zod, react-router |  | Prompt 5 |

## 6. Known issues and gotchas

Seeded from planning. Add more as they appear.

- Render free spins down after 15 minutes and takes about a minute to wake. The login page pings `/health`. API client retries once on timeout.
- Render free CPU is 0.1. Anything heavy must be a script in Actions.
- Supabase free direct host is IPv6 only. Use the session pooler string. With a transaction pooler set `prepare_threshold=None`.
- Supabase free pauses after a week without activity. The weekly job keeps it alive.
- ReportLab built-in fonts lack the Rupee sign. Register the Plex TTFs.
- LightGBM in `python:slim` needs `libgomp1`.
- `email-validator` rejects special-use domains such as `.test` and `.local`.
- PostgreSQL `UNIQUE NULLS NOT DISTINCT` needs PG 15 or newer (local image is pg16, Supabase is 15 or newer).
- pandas 3 changes default string dtype and copy-on-write semantics. Avoid chained assignment.
- Gemini thinking models can return message content as a list of blocks. Use `message_text()` helper.
- LangGraph checkpoint tables are created by `setup()`, exclude them from Alembic autogenerate, enable RLS on them afterwards.
- GitHub scheduled workflows can run late and are disabled after 60 days of repo inactivity (public repos). Keep `workflow_dispatch`.
- Free Gemini tier may use inputs for product improvement. Synthetic data only.
- Lunar festival dates can differ by one day across sources. Keep `is_verified` honest.

Found while building Prompt 1:

- The system drive was at 99 percent. A full disk makes Docker Desktop fail with "read-only file system" during image extraction and then hang. Keep several GB free before building the API image, and `docker builder prune` reclaims cache without touching images or volumes.
- OneDrive locks files inside a `.venv` in the repo and `uv run` then fails with "Access is denied". Keep the virtualenv outside the synced folder (`UV_PROJECT_ENVIRONMENT`), and keep `[tool.uv] package = false` so uv never rebuilds the project.
- Compose bind mounts `./backend` over `/app`, so the Docker virtualenv must not live in `/app/.venv`. It is `/opt/venv`.
- On Windows, GNU Make and uv may not be on PATH in a fresh shell. `winget install ezwinports.make` needs a new shell, and `make ... UV="python -m uv"` works when only the pip installed uv exists.
- FastAPI 0.143 mounts included routers lazily, so `scope["route"].path` is relative to the prefix (`/health` instead of `/api/v1/health`). `core/middleware.py::route_template` rebuilds the full template.
- An exception that escapes every middleware is answered by Starlette `ServerErrorMiddleware`, outside our stack, so that 500 would lack the request id, security and CORS headers. `UnhandledErrorMiddleware` sits innermost and converts it to the envelope first.
- `pydantic-settings` only wraps `ValueError` in `ValidationError`. `ConfigError` is a `RuntimeError`, so a bad production config fails at import with the full list of problems.
- A recreated `public` schema has no `USAGE` for `PUBLIC`, unlike a fresh database. The test reset grants it, otherwise a probe role cannot even see the tables.
- `PUBLIC` keeps `USAGE` on schema `public`, so `has_schema_privilege('anon', 'public', 'USAGE')` stays true after revoking from `anon`. Check the explicit ACL instead.
- `window` is a reserved word. SQLAlchemy quotes the column, but raw text in a CHECK must quote it too (`enum_check` does).
- Alembic `env.py` calls `fileConfig`, which replaces the application logging. Programmatic runs set `config.attributes["configure_logger"] = False`.
- ruff isort treats `alembic` as first party because `backend/alembic/` exists. `known-third-party = ["alembic"]` fixes it.
- `alembic downgrade base` followed by `upgrade head` leaves `tax_rates` and `calendar_events` empty. Reference data comes from `python -m app.jobs.run migrate`, not from Alembic.
- Text written through some editor and shell tools can turn a typed unicode escape for a long dash into the real character. Verify with `scripts/check_copy.py` after writing any source or doc that mentions the long dashes, and build such characters with `chr()` in scripts.
- Apostrophes inside a shell heredoc can break the command wrapper. Write files with the editor tools.

## 7. Measurements (fill in as you go)

| Item | Value | Date |
|---|---|---|
| Argon2 hash time on Render free | | |
| API resident memory (idle, after export) | 178 MiB for the whole dev container (reload watcher plus worker), before any export. Budget is 400 MB | 2026-10-13 |
| Full seed size (MB) | | |
| Light pipeline time per tenant | | |
| Full pipeline time per tenant | | |
| Tenant WAPE vs baseline WAPE | | |
| Agent eval grounding pass rate | | |
| Test counts and coverage per prompt | Prompt 1: 352 tests, 99 percent total, 95 to 100 percent per `app.core` module, suite takes about 75 s | 2026-10-13 |
| API dev image size | 1.29 GB (includes ml and agents packages) | 2026-10-13 |
| API runtime image size | 1.0 GB. Verified: runs as uid 10001, migrates on start, Docker healthcheck healthy, lightgbm imports (libgomp) | 2026-10-13 |
| Migration upgrade from empty | about 3 s for 10 revisions | 2026-10-13 |

## 8. Session handoff (rewrite at the end of every session)

- State: **Prompt 1 complete** (P1.01 to P1.16). `make up` starts Postgres (pgvector), the API and a placeholder web page. `make migrate` builds all 51 tables, RLS, views and reference data. Health endpoints respond. 352 tests, lint, strict types and the copy check are green. Nothing is pushed (there is no remote).
- Last action: verification gate run on a fresh volume on 2026-10-13, then context files updated.
- Next step: **Prompt 2, auth and transactional core**. Start with `progress.md` P2.01. The pieces it plugs into already exist: `TenantRepo`, `AppError` and the envelope, `create_app`, `api/v1/router.py` (add routers there), `tests/api/conftest.py` fixtures, `two_tenants` and the factories in `tests/factories.py` (users have a placeholder password hash today), `core/clock.py` for token times.
- Open problems: none blocking. The host system drive is nearly full (see section 6), tell the human.
- Notes for the next session:
  - Run commands from `backend/` with `UV_PROJECT_ENVIRONMENT` pointing outside OneDrive, or use `make ... UV="python -m uv"`.
  - Never write the long dash characters literally in source or docs, use escapes (`D-052`).
  - Prompt 3 must flip `is_verified` for the calendar in `app/jobs/reference_data.py` (`D-047`), and Prompt 7 must run the RLS statement from migration 0010 after `PostgresSaver.setup()`.
  - The `frontend` CI job is switched off with `if: false` until P5.13.
  - `rejected(db, ...)` in `tests/conftest.py` is the way to assert database refusals.
