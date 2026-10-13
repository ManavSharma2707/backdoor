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
