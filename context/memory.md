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

(No entries yet beyond the locked list above.)

## 5. Pinned versions

Fill in at install time (`uv pip list`, `npm ls --depth=0`).

| Package | Version | Date | Note |
|---|---|---|---|
| python | 3.12.x | | |
| node | 22.x | | |
| fastapi | | | |
| sqlalchemy | | | |
| psycopg | | | |
| alembic | | | |
| pydantic | | | |
| pyjwt | | | |
| argon2-cffi | | | |
| pandas | | | |
| numpy | | | |
| scikit-learn | | | |
| lightgbm | | | |
| reportlab | | | |
| xlsxwriter | | | |
| langgraph | (1.2.x line confirmed in planning) | 2026-10-13 | |
| langchain-core | | | |
| langchain-google-genai | | | |
| google-genai | | | |
| react | | | |
| vite | | | |
| tailwindcss | | | |
| @tanstack/react-query | | | |
| recharts | | | |
| zod | | | |
| react-router | | | |

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

## 7. Measurements (fill in as you go)

| Item | Value | Date |
|---|---|---|
| Argon2 hash time on Render free | | |
| API resident memory (idle, after export) | | |
| Full seed size (MB) | | |
| Light pipeline time per tenant | | |
| Full pipeline time per tenant | | |
| Tenant WAPE vs baseline WAPE | | |
| Agent eval grounding pass rate | | |
| Test counts and coverage per prompt | | |

## 8. Session handoff (rewrite at the end of every session)

- State: planning complete, context files written, **no code exists yet**.
- Last action: context files created on 2026-10-13.
- Next step: Prompt 1 (Foundation and database). Start with `progress.md` P1.01.
- Open problems: none.
- Notes for the next session: none.
