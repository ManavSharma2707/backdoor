# Backroom

A retail inventory and procurement app. Its main output is one weekly buying plan, built from forecasts, usable stock, expiry, supplier terms and a budget. All data in the demo is simulated.

This file is the setup and daily use guide. The full specs are in `context/`.

## What works today

Sign in, overview, products, sales (fast bill entry), purchases (orders and goods receipt), stock (levels, batches and expiry, movements, counts, out of stock history) and settings. The Monday plan, trends and assistant screens are placeholders and arrive in later prompts (see `context/progress.md`).

## 1. Set up on a new machine

You need Docker Desktop and Git. Node 22 is only needed to run the frontend checks or the web app outside Docker.

1. Clone the repo and open a terminal in its folder.

2. Copy the settings file:

   ```
   cp .env.example .env
   ```

   Open `.env` and set:

   - `DEMO_OWNER_PASSWORD`: the password for all demo logins, 12 or more characters.
   - `JWT_SECRET` and `JOB_TOKEN`: long random text.
   - Optional: `DEMO_LOGIN_ENABLED=true` shows one click demo buttons on the sign in page.

   Never commit `.env`. It is git-ignored.

3. Start the database, API and web app. The first start installs the web packages and takes a few minutes:

   ```
   docker compose up -d --build
   ```

4. Load the four demo businesses (about 6 minutes), then create their weekly plans (a few minutes):

   ```
   docker compose exec api python -m seed.run --tenants all
   docker compose exec api python -m app.jobs.run backfill --tenant all --weeks 8
   docker compose exec api python -m app.jobs.run monday --tenant all --profile full --force
   ```

   The seed is deterministic, so every machine gets the same data. The database lives in a Docker volume and does not travel with the repo.

5. Open http://localhost:5173 and sign in with the password from step 2:

   | Email | Business |
   |---|---|
   | `owner.fmcg-a@backroom-demo.com` | Grocery store |
   | `owner.fmcg-b@backroom-demo.com` | Grocery store |
   | `owner.med-a@backroom-demo.com` | Medical store |
   | `owner.med-b@backroom-demo.com` | Medical store |

   API docs: http://localhost:8000/api/v1/docs

## 2. Daily use

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop (keeps the data) | `docker compose down` |
| Watch logs | `docker compose logs -f --tail=100` |
| Apply a changed `.env` | `docker compose up -d api` |
| Reseed from scratch | `docker compose exec api python -m seed.run --tenants all --reset`, then the two `app.jobs.run` commands from step 4 |
| Wipe everything including the database | `docker compose down -v` |
| Create this week's plan again | `docker compose exec api python -m app.jobs.run monday --tenant all --profile full --force` |

`make` is optional. Every target in the `Makefile` is a plain `docker compose` or `npm` command, and `make help` lists them.

## 3. What to try

- Overview (`/`): needs attention, key numbers, sales trend, days of stock by category.
- New bill (`/sales/new`): type a product name, press Enter to add it, press Ctrl+Enter to save.
- New order (`/purchases/new`): pick a supplier, add a product, save and mark as sent. Open the order and use Receive goods.
- Stock (`/stock`): the five tabs, Record adjustment and Start stock count.
- Products (`/products`): search, filters, detail tabs, Add product.
- Component gallery (`/_ui`): every component and state. Development only, no sign in needed.
- Narrow the browser window to see the phone layout.

## 4. Checks

Frontend, from `frontend/`:

```
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Backend, from `backend/` (the tests need the Postgres container running):

```
uv sync
uv run ruff check .
uv run mypy app/core app/engine
uv run pytest
```

Copy rules (no long dashes, no banned words), from the repo root:

```
python scripts/check_copy.py
```

After an API change, regenerate the frontend types:

```
docker compose exec api python -m app.jobs.run openapi
cd frontend && npm run openapi-types
```

## 5. Running the web app without Docker

```
cd frontend
npm ci
npm run dev
```

It proxies `/api` to http://localhost:8000, so the API container must be up. Set `VITE_PROXY_TARGET` to use another API address.

## 6. Screenshots and the end to end flow

These need the stack up, the web app on port 5173 and the demo password exported. On Windows Git Bash, prefix with `MSYS_NO_PATHCONV=1`.

```
cd frontend
set -a; . ../.env; set +a
node scripts/screenshots.mjs owner.fmcg-a@backroom-demo.com / /products /stock
node scripts/smoke.mjs
```

Screenshots go to `frontend/screenshots/` (git-ignored). The smoke script adds a sale, creates and receives an order and adjusts stock. It writes real records to the demo database, so use it on demo data only. Both scripts use the Chrome installed on the machine.

## 7. Troubleshooting

- The page loads but you are signed out after a reload: the API needs `CORS_ORIGINS` to include `http://localhost:5173`. The compose file sets it, so run `docker compose up -d api`.
- Saving the first bill fails with a duplicate key error: the database was seeded before the sequence fix. Reseed with `--reset`.
- The web service is slow on first start: it is installing packages. Check `docker compose logs web`.
- Docker will not start or hangs after the disk fills up: free several GB, then restart Docker Desktop. More in `context/memory.md`, section 6.
- If the repo is in OneDrive or another synced folder, keep any Python virtualenv outside it (`context/memory.md`, section 6).
- The weak demo password warning during seeding is expected if your password is on the common list. It does not stop the seed.

## 8. Notes

- Demo data is simulated and never described as real customer results.
- Only synthetic data may be sent to any external AI service.
- Nothing is pushed or deployed from here. Deployment steps are in `context/deployment.md`.
