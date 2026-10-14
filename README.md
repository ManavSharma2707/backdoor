# Backroom

A retail inventory and procurement app. Its main output is one weekly buying plan, built from forecasts, usable stock, expiry, supplier terms and a budget. All data in the demo is simulated.

This file is the short setup guide. The full specs are in `context/`.

## Run it on a new machine

You need Docker Desktop, Git, and Node 22 only if you want to run the web app outside Docker.

1. Copy the settings file and set a demo password (12 or more characters):

   ```
   cp .env.example .env
   ```

   Open `.env` and fill in `DEMO_OWNER_PASSWORD`. Change `JWT_SECRET` and `JOB_TOKEN` to long random text. Never commit `.env`.

2. Start the database, API and web app. The first start installs the web packages and takes a few minutes:

   ```
   docker compose up -d --build
   ```

3. Load the four demo businesses (about 6 minutes), then create their weekly plans (a few minutes):

   ```
   docker compose exec api python -m seed.run --tenants all
   docker compose exec api python -m app.jobs.run backfill --tenant all --weeks 8
   docker compose exec api python -m app.jobs.run monday --tenant all --profile full --force
   ```

4. Open http://localhost:5173 and sign in as one of:

   - `owner.fmcg-a@backroom-demo.com` (grocery)
   - `owner.fmcg-b@backroom-demo.com` (grocery)
   - `owner.med-a@backroom-demo.com` (medical store)
   - `owner.med-b@backroom-demo.com` (medical store)

   The password is the `DEMO_OWNER_PASSWORD` you set. The API docs are at http://localhost:8000/api/v1/docs.

Set `DEMO_LOGIN_ENABLED=true` in `.env` and restart the api (`docker compose up -d api`) if you want one click demo buttons on the sign in page.

## Notes

- `make` is optional. Every `make` target in the `Makefile` is a plain `docker compose` or `npm` command.
- If the repo lives in a OneDrive or other synced folder on Windows, keep the Python virtualenv outside it (see `context/memory.md`, section 6).
- Frontend checks, from `frontend/`: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- Backend checks, from `backend/`: `uv sync`, then `uv run ruff check .`, `uv run mypy app/core app/engine`, `uv run pytest`. The tests need the Postgres container running.
- The Monday plan, trends and assistant screens are not built yet. See `context/progress.md`.
