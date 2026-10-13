# Deployment

Targets (all free tiers): frontend on **Vercel**, API on **Render** (Docker), database on **Supabase**, scheduled heavy job on **GitHub Actions**. Local development uses Docker Compose.

Facts checked on 13 Oct 2026 (re-check when deploying, plans change):
- **Render free web service**: 512 MB RAM, 0.1 CPU, spins down after 15 minutes without inbound traffic and takes about a minute to wake, ephemeral filesystem, shared monthly free instance hours, may restart at any time. It cannot do heavy compute. Free Render Postgres expires after 30 days, so we do not use it.
- **Supabase free**: 500 MB database, projects pause after 1 week of inactivity, 2 free projects, pgvector included. The direct database host is IPv6 only on the free plan, so IPv4 clients (Render, GitHub Actions) must use the **session pooler** connection string.
- **Gemini API free tier**: Flash and Flash-Lite families are free with rate limits, Pro models are paid, inputs and outputs on the free tier can be used by Google to improve products. Synthetic data only.
- **GST** structure used by the seed: 0, 5, 18, 40 percent slabs effective 22 Sep 2025.

---

## 1. Local development

`docker-compose.yml` services:

| Service | Image or build | Notes |
|---|---|---|
| `db` | `pgvector/pgvector:pg16` | env `POSTGRES_USER=backroom POSTGRES_PASSWORD=backroom POSTGRES_DB=backroom`, volume `pgdata`, healthcheck `pg_isready -U backroom`, port 5432. An init script creates database `backroom_test` and extensions `vector citext pg_trgm pgcrypto` in both |
| `api` | build `./backend` (dev target) | command `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`, mounts `./backend:/app`, env from `.env`, depends on `db` healthy, runs `alembic upgrade head` first |
| `web` | `node:22-alpine` | working dir `/app`, mounts `./frontend`, command `npm run dev -- --host 0.0.0.0`, port 5173, env `VITE_API_BASE_URL=/api/v1`, Vite proxy to `http://api:8000` |

`make up` starts all, `make seed` runs `docker compose exec api python -m seed.run --tenants all` (needs `DEMO_OWNER_PASSWORD` in `.env`), `make job-monday` runs `docker compose exec api python -m app.jobs.run monday --profile full --all-tenants`.

Local secrets: `.env` copied from `.env.example`, git ignored. Compose reads it when present (`required: false`), so the stack also starts without one.

Host tooling: `make lint`, `make typecheck` and `make test` run `uv` on the host against the database published on `localhost:5432`, so run `make up` (or `docker compose up -d db`) first. Docker only runs the stack. On Windows install GNU Make (`winget install ezwinports.make`) and `uv` (`pip install uv` or the uv installer), and keep the virtualenv outside any OneDrive folder. Free about 5 GB on the system drive before the first image build: the API image carries pandas, scikit-learn, LightGBM and the LangChain packages.

## 2. Environment variables

### Backend

| Variable | Example or default | Notes |
|---|---|---|
| `APP_ENV` | `local`, `production` | Production enables strict checks |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@aws-0-ap-south-1.pooler.supabase.com:5432/postgres` | Session pooler string from Supabase (user is `postgres.<project-ref>`). Local: `postgresql+psycopg://backroom:backroom@db:5432/backroom` |
| `DATABASE_POOL_SIZE` | 5 | Keep small, Supabase free has limited connections |
| `DATABASE_MAX_OVERFLOW` | 2 | Extra connections allowed above the pool size |
| `DATABASE_TRANSACTION_POOLER` | false | Set true only with a Supabase transaction pooler (port 6543). Turns off prepared statements |
| `JWT_SECRET` | 32+ random bytes base64 | Required in production |
| `JWT_ISSUER` | `backroom` | |
| `JWT_AUDIENCE` | `backroom-web` | |
| `ACCESS_TOKEN_MINUTES` | 15 | |
| `REFRESH_TOKEN_DAYS` | 14 | |
| `COOKIE_SECURE` | true (false only local) | |
| `CORS_ORIGINS` | `https://backroom.vercel.app,http://localhost:5173` | Comma list |
| `JOB_TOKEN` | 32+ random bytes | For `/jobs/*` |
| `ALLOW_REGISTRATION` | false | |
| `DEMO_LOGIN_ENABLED` | false | Only for synthetic tenants |
| `ALLOW_DEMO_RESET` | false | |
| `SIMULATE_WEEKLY` | false | Actions workflow extends demo history |
| `AGENTS_ENABLED` | true | |
| `GEMINI_API_KEY` | | Free key, synthetic data only |
| `GEMINI_MODEL_FAST` | chosen in Prompt 7 | Flash-Lite style model with function calling |
| `GEMINI_MODEL_SMART` | chosen in Prompt 7 | Flash style model |
| `GEMINI_EMBED_MODEL` | chosen in Prompt 7 | Supports `output_dimensionality` |
| `EMBED_DIM` | 768 | Must match the `vector(768)` column |
| `LOG_LEVEL` | INFO | |
| `DEMO_OWNER_PASSWORD` | 12+ chars | Seed only, never committed |
| `SEED_BASE` | 20261011 | |

### Frontend (Vite, build time)
| Variable | Notes |
|---|---|
| `VITE_API_BASE_URL` | `/api/v1` |
| `VITE_CHAT_DIRECT_URL` | Optional absolute Render URL for the SSE stream if the Vercel rewrite buffers |
| `VITE_APP_NAME` | `Backroom` |

`.env.example` lists all names with safe placeholders. The backend settings class lists the same names with defaults and validation.

## 3. Backend image

`backend/Dockerfile` (multi stage):
- Stage `builder`: `python:3.12-slim`, copy `uv` from `ghcr.io/astral-sh/uv:0.13.0` (pinned), copy `pyproject.toml` and `uv.lock`, `uv sync --frozen --no-dev --no-install-project`, copy source, `uv sync --frozen --no-dev`.
- Stage `runtime`: `python:3.12-slim`, `apt-get install -y --no-install-recommends libgomp1 libpq5 curl` (LightGBM needs libgomp), copy the virtualenv (`/opt/venv`, outside `/app` so the dev bind mount cannot hide it) and source, create user `app` (uid 10001), `ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2`, `HEALTHCHECK CMD curl -fsS http://localhost:${PORT:-8000}/api/v1/health || exit 1`, `CMD ["./start.sh"]`.
- Dev target adds dev dependencies and `--reload`.
- Fonts in `app/assets/fonts/` are copied in (needed for PDF).

`start.sh`:
```sh
#!/bin/sh
set -e
python -m app.jobs.run migrate        # alembic upgrade head under pg_advisory_lock
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
```
Memory settings: one worker, `PYTHONMALLOC` default, set `MALLOC_ARENA_MAX=2` to reduce fragmentation. Lazy import heavy libs (`lightgbm`, `langgraph`, `reportlab`, `xlsxwriter`). Check resident memory after startup and after a report export, record in `memory.md`. Budget 400 MB.

## 4. Supabase setup (one time, manual steps for the human)

1. Create a project, region closest to India (Mumbai or Singapore), note the database password.
2. Connect screen: copy the **Session pooler** connection string. Put it in `DATABASE_URL` for Render and GitHub Actions (replace the scheme with `postgresql+psycopg://`).
3. Extensions: `vector`, `citext`, `pg_trgm` (migration `0001` runs `CREATE EXTENSION IF NOT EXISTS`, which works on Supabase as the postgres role).
4. After migrations, the migration `0010` enables RLS on all tables and revokes grants from `anon` and `authenticated`. Verify in the dashboard that no table is exposed (Advisors, security).
5. Seed from a laptop: `DATABASE_URL=<session pooler> python -m seed.run --tenants all` (COPY over network, allow 20 to 30 minutes). Check `python -m seed.size_report` stays under 400 MB.
6. Backups: free plan has no point-in-time recovery. Run `scripts/db_dump.sh` (`pg_dump --format=custom`) before risky changes and monthly. The weekly Monday job also keeps the project from pausing (a project with no activity for a week is paused).

## 5. Render (API)

`render.yaml` (Blueprint):
```yaml
services:
  - type: web
    name: backroom-api
    runtime: docker
    dockerContext: ./backend
    dockerfilePath: ./backend/Dockerfile
    plan: free
    region: singapore
    healthCheckPath: /api/v1/health
    autoDeploy: true
    envVars:
      - key: APP_ENV
        value: production
      - key: CORS_ORIGINS
        sync: false
      - key: DATABASE_URL
        sync: false
      - key: JWT_SECRET
        generateValue: true
      - key: JOB_TOKEN
        generateValue: true
      - key: GEMINI_API_KEY
        sync: false
      - key: COOKIE_SECURE
        value: "true"
```
Notes: set the remaining variables in the dashboard. Render free has no persistent disk and no private networking, nothing is stored locally. Autodeploy from the connected GitHub repo happens only after the human pushes. Migrations run at container start (pre-deploy commands are not relied on).

The free instance is slow (0.1 CPU): the API runs only light work. Do not run the full pipeline or LightGBM training there. Report regeneration from the UI uses the `light` profile. Keep the app responsive by running exports in a thread and keeping payloads small.

## 6. Vercel (frontend)

`frontend/vercel.json`:
```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://<render-service>.onrender.com/api/:path*" },
    { "source": "/((?!api/).*)", "destination": "/index.html" }
  ],
  "headers": [
    { "source": "/(.*)", "headers": [
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
      { "key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()" },
      { "key": "Content-Security-Policy", "value": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://<render-service>.onrender.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" }
    ] }
  ]
}
```
Project settings: root directory `frontend`, framework Vite, build `npm run build`, output `dist`. Rewrites to an external host proxy the request, so the refresh cookie is first party. Test SSE through the rewrite. If it buffers or times out, set `VITE_CHAT_DIRECT_URL` to the Render URL and rely on bearer auth plus the CORS allowlist for that stream only.

## 7. GitHub Actions

### CI: see `testing-strategy.md` section 9.

### Monday pipeline (`.github/workflows/monday-job.yml`)
```yaml
name: monday-job
on:
  schedule:
    - cron: "30 0 * * 1"     # 00:30 UTC = 06:00 IST every Monday
  workflow_dispatch:
    inputs:
      tenant: { description: "Tenant slug or all", default: "all" }
      profile: { description: "light or full", default: "full" }
      force:   { description: "Create a new version", default: "false" }
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      APP_ENV: production
      AGENTS_ENABLED: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen --project backend
      - name: Optional demo week
        if: ${{ vars.SIMULATE_WEEKLY == 'true' }}
        run: uv run --project backend python -m app.jobs.run simulate-week
      - name: Run Monday pipeline
        run: >
          uv run --project backend python -m app.jobs.run monday
          --tenant "${{ inputs.tenant || 'all' }}"
          --profile "${{ inputs.profile || 'full' }}"
          ${{ inputs.force == 'true' && '--force' || '' }}
      - name: Keep API warm (optional)
        run: curl -fsS --retry 5 --retry-delay 20 --max-time 120 "${{ secrets.API_URL }}/api/v1/health" || true
```
Notes: the job connects to Supabase directly using the session pooler and runs the same code as the API. Scheduled workflows can be delayed by up to an hour and GitHub disables schedules on repos with no activity for 60 days (public repos), so re-enable if needed and keep `workflow_dispatch`. Secrets: `DATABASE_URL`, `GEMINI_API_KEY`, `API_URL`. Variables: `SIMULATE_WEEKLY`. `JOB_TOKEN` is only needed if the endpoint trigger is used instead.

Alternative trigger through the API (`POST /api/v1/jobs/monday-report`, `X-Job-Token`) is kept for light runs and wake-up, never for full runs.

Exit codes: the script exits non zero if any tenant failed so the Action shows red, and writes a summary table to `$GITHUB_STEP_SUMMARY`.

## 8. Release checklist (human, after the final prompt)

1. `make lint test` green locally, CI green on the pushed branch.
2. Supabase project created, extensions available, `DATABASE_URL` set in Render and Actions.
3. Seed loaded, `seed.validate` and `size_report` pass against Supabase.
4. Render deploy healthy at `/api/v1/health/ready`.
5. Vercel deploy with correct rewrite target, login works through the proxy, refresh cookie set with the Vercel domain.
6. Run the workflow with `workflow_dispatch` once, confirm report created and agent review attached.
7. Rotate any key used during development, confirm no secret appears in git history (`git log -p | grep` checks for key patterns, human responsibility).
8. Decide demo login: set `DEMO_LOGIN_ENABLED=true` only if the deployment holds synthetic data only.
9. Read the README limitations section and add the live link.

## 9. Operating notes

- Cold start: first request after idle takes about a minute. The login page warms the API. The Monday workflow pings health at the end so the first Monday visit is faster.
- Logs: Render dashboard. Use `request_id` in error messages to correlate.
- Monitoring: `/health/ready` for uptime checks (an external free pinger would also keep Render awake, optional and not required).
- Data growth: weekly simulation adds a few MB per month. Check `size_report` monthly.
- Cost control: Gemini calls only on user chat and on the Monday run. Per user limits in `api-spec.md`.
