# CLAUDE.md

Project: **Backroom** (working name), a multi-tenant retail inventory and procurement platform. Its main output is one weekly buying plan, the "Monday plan", built from demand forecasts, usable stock, expiry exposure, supplier terms and a budget. Four synthetic Indian retail businesses (two FMCG, two medical stores) ship as demo tenants. An agent layer (RAG + LangGraph + Gemini) explains the numbers but never computes or changes them.

This file is the operating manual for every Claude Code session on this repo. Follow it literally.

---

## 1. Read first, every time

At the start of every session and every new prompt, before writing any code:

1. Read this file.
2. Read `context/memory.md` (decisions, defaults, handoff notes).
3. Read `context/progress.md` (what is done, what is next).
4. Read `context/README.md` (index), then the specs relevant to the task using the table below.
5. Run `git status` and `git log --oneline -20` to see the real state of the repo.
6. Tell the user in 3 to 6 lines what exists, what you will do now, and anything that looks inconsistent. Then continue without waiting, unless something blocks you.

Read again, not from memory, whenever you start a new milestone or touch a domain you have not touched in this session.

| Task area | Must read |
|---|---|
| Anything | `memory.md`, `progress.md`, `architecture.md` |
| Tables, migrations, models, queries | `database.md` |
| Auth, tokens, permissions, secrets | `security.md`, `database.md` (auth tables), `api-spec.md` |
| Endpoints, schemas, errors, pagination | `api-spec.md` |
| Forecasting, replenishment, budget, expiry, dead stock, data checks | `engine-spec.md`, `india-calendar.md` |
| Monday report, PDF, Excel, CSV | `report-spec.md`, `engine-spec.md` |
| Synthetic data, seed scripts | `seed-data-spec.md`, `india-calendar.md`, `database.md` |
| Chatbot, RAG, agents, LangGraph | `agents-spec.md`, `security.md`, `api-spec.md` |
| Any library usage | `libraries.md` (do not search the web for API usage first) |
| Any frontend work | `ui-design-system.md`, `ui-copywriting.md`, `ui-screens.md` |
| Tests, CI | `testing-strategy.md` |
| Docker, hosting, env vars, GitHub Actions | `deployment.md` |

`PROMPT-BOOKLET.md` is for the human. Do not read it and do not follow it.

---

## 2. The context files are the source of truth

- If code and a spec disagree, the spec wins, unless you have a good reason. In that case change the spec in the same commit, and add a `Spec change` entry to `context/memory.md` explaining why.
- Never delete spec content to make a conflict go away. Amend it.
- Keep the specs current while you build. This is part of the task, not an extra.

### Update rules (mandatory)

| When | Update |
|---|---|
| You finish a checklist item | Tick it in `progress.md` and add the date, e.g. `- [x] P2.04 ... (2026-10-15)` |
| You make a decision the specs do not cover | Append to the decision log in `memory.md` (next `D-xxx` id, date, context, choice, alternatives, consequence) |
| You install a dependency | Record the exact version under "Pinned versions" in `memory.md`. Add usage notes to `libraries.md` if the API surprised you |
| You hit a gotcha that cost time | Add it to "Known issues and gotchas" in `memory.md` |
| You add a file that future sessions must know about | Add it to `context/README.md` |
| End of every session | Rewrite "Session handoff" in `memory.md`: state, next step, open problems |

---

## 3. Git rules (strict)

You may **commit**. You may not **push**.

Allowed: `git status`, `git diff`, `git log`, `git add <explicit paths>`, `git commit`, `git restore` for your own uncommitted changes, `git branch` (read only).
Forbidden, no exceptions: `git push` (any form), `git remote add/set-url`, `git fetch` or `pull` from remotes, `--force`, `--no-verify`, `git reset --hard`, `git clean -fd`, history rewrites of earlier commits, creating tags or releases, `gh` write commands.

Work on `main`. The human pushes.

### Commit cadence
- Commit at **logical checkpoints**, when one coherent unit works and its tests and lint pass. Expect roughly 4 to 8 commits per prompt.
- A commit is a bundle: for example "all auth endpoints plus tests plus the docs that describe them". It is never one file, never "wip", never "fix typo" spam, never a mix of unrelated changes.
- Every commit must leave the repo building and the test suite green.
- Context file updates ship in the same commit as the code they describe, or in one `docs(context)` commit at the end of a milestone.
- Before committing: run formatters, linters, relevant tests, `python scripts/check_copy.py`, then review `git status` and `git diff --staged`. Stage explicit paths, not `git add -A`. Make sure no `.env`, key, dump or build output is staged.

### Message format (Conventional Commits)

```
type(scope): imperative summary, lowercase, max 72 chars

Short paragraph on what changed and why.

- Concrete change one
- Concrete change two
- Tests or docs touched

Refs: P2.03, P2.04
```

Types: `feat fix refactor perf test docs chore build ci`.
Scopes: `auth db catalogue ledger sales purchasing inventory seed forecast replenishment report export agents rag chat ui infra docs context`.

Do not add co-author trailers, tool signatures, emoji or session links to commit messages. The user owns the history.

---

## 4. Engineering rules

**General**
- Python 3.12, type hints everywhere, `ruff` clean, `mypy` clean on `app/engine` and `app/core`. TypeScript strict, ESLint clean.
- Small modules, pure functions in `app/engine` (no DB access, no globals, no clock calls; pass `as_of` in).
- No `print`. Use structured logging. No bare `except`. No dead code, no commented-out code, no TODO without a `progress.md` item.
- Money and quantities use `Decimal` and `NUMERIC`. Never `float` for money. Engine math may use `float64`/`float32` arrays, convert at the boundary and round only for display.
- Business dates are `date` in `Asia/Kolkata`. Timestamps are `timestamptz` in UTC. Never call `datetime.now()` directly: use `app/core/clock.py`.
- Every tenant-owned query is filtered by `tenant_id` from the authenticated context, never from request input. Use the repository base class that enforces this.
- Mutating endpoints that create ledger records are transactional and idempotent (see `api-spec.md`).
- History is never edited silently. Corrections are new records (void, reversal, adjustment).
- Every number the user sees must be traceable to a stored record. The engine is the only producer of quantities. LLM output never becomes a quantity.
- Do not invent real-world claims. Demo data is synthetic, labelled synthetic, and never described as customer results.

**Security** (full list in `security.md`)
- No secrets in code, logs, tests, fixtures or commits. `.env` is git-ignored, `.env.example` is complete.
- Validate all input with Pydantic. Authorise on the server. Test tenant isolation for every new endpoint.
- Free-tier Gemini may train on prompts. Only synthetic data goes to it. Never wire real customer data to the free key.

**UI** (full list in the `ui-*.md` files)
- Follow the design system exactly. No new colours, fonts, radii or shadows outside the tokens.
- All user-facing text lives in `frontend/src/copy/en.ts` and follows `ui-copywriting.md`.
- **No em dashes and no en dashes anywhere** in UI text, error messages, emails, PDFs, Excel output, chatbot output, seed corpus text, or context files. Use a comma, colon, full stop or the word "to". `scripts/check_copy.py` enforces this and runs in CI and before every commit.
- The UI must not look generated: see the "Anti-template checklist" in `ui-design-system.md`.

**Testing** (see `testing-strategy.md`)
- Write tests with the code, not after. Engine and ledger code need property tests. Every endpoint needs a tenant isolation test. Bug fix means a regression test first.

---

## 5. How to work

- Work in vertical slices that run end to end, in the order given in `progress.md`.
- Prefer the simplest design that satisfies the spec. The specs already pick the stack. Do not swap libraries without a decision entry and a reason.
- Decide small things yourself and log them in `memory.md`. Ask the user only when the choice is expensive to reverse and the specs do not answer it. Never stop for permission to continue routine work.
- If something in the specs looks wrong or impossible, say so, propose the fix, update the spec, log it.
- Keep the app runnable at every checkpoint: `docker compose up` must work.
- Respect free-tier limits (see `deployment.md`): Render free is 512 MB RAM and 0.1 CPU, Supabase free is 500 MB of data. Heavy compute runs in GitHub Actions, not in the API container.
- Library usage: use `libraries.md` first. If you must check a version, use the package manager (`uv pip index versions`, `npm view`), then record it in `memory.md`.

## 6. Definition of done for any task

1. Behaviour matches the spec, including edge cases listed there.
2. Tests written and passing, including tenant isolation where relevant.
3. Lint, types, copy check pass.
4. `progress.md` ticked, `memory.md` updated, specs amended if they changed.
5. Committed in a clean, bundled, formally worded commit. Not pushed.

## 7. Commands (created in Prompt 1)

```
make up | down | logs        docker compose for db, api, web
make migrate                 alembic upgrade head
make revision m="message"    alembic autogenerate
make seed | seed-reset       demo data for all four tenants
make job-monday              run the Monday pipeline locally
make test | test-backend | test-frontend
make lint | format | typecheck | check-copy
make openapi-types           regenerate frontend API types
make dump                    pg_dump to ./backups (git-ignored)
```

## 8. Repo map

```
CLAUDE.md
context/                 source-of-truth specs
backend/                 FastAPI app, engine, agents, seed generator, tests
frontend/                React app
docker-compose.yml  Makefile  render.yaml  .env.example
.github/workflows/       ci.yml, monday-job.yml
scripts/                 check_copy.py, db_dump.sh
```

Details are in `context/architecture.md`.
