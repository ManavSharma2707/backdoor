# Backroom developer commands. Needs Docker, uv, Node 22 and GNU Make.
# Docker runs the database, API and web. Python tooling (lint, types, tests) runs on the host.
#
# If uv is not on your PATH but installed through pip:  make test UV="python -m uv"
# If the repo lives in a synced folder (OneDrive), keep the virtualenv outside it:
#   set UV_PROJECT_ENVIRONMENT to a folder outside the sync, for example ~/.venvs/backroom

UV ?= uv
PYTHON ?= python
COMPOSE ?= docker compose
export UV_LINK_MODE ?= copy

.PHONY: help up down logs migrate revision seed seed-reset job-monday \
	test test-backend test-frontend lint lint-backend lint-frontend format typecheck \
	check-copy openapi-types dump

help:
	@echo "make up | down | logs        docker compose for db, api, web"
	@echo "make migrate                 alembic upgrade head and reference data"
	@echo "make revision m=\"message\"    alembic autogenerate"
	@echo "make seed | seed-reset       demo data for all four tenants"
	@echo "make job-monday              run the Monday pipeline locally"
	@echo "make test | test-backend | test-frontend"
	@echo "make lint | format | typecheck | check-copy"
	@echo "make openapi-types           regenerate frontend API types"
	@echo "make dump                    pg_dump to ./backups"

# ---------------------------------------------------------------- stack

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

migrate:
	$(COMPOSE) exec api python -m app.jobs.run migrate

revision:
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

seed:
	$(COMPOSE) exec api python -m seed.run --tenants all

seed-reset:
	$(COMPOSE) exec api python -m seed.run --tenants all --reset

job-monday:
	$(COMPOSE) exec api python -m app.jobs.run monday --profile full --all-tenants

dump:
	sh scripts/db_dump.sh

# ---------------------------------------------------------------- quality

test: test-backend test-frontend

test-backend:
	cd backend && $(UV) run pytest -m "not agent_eval_live" --cov=app --cov-report=term

test-frontend:
	cd frontend && npm run test --if-present

lint: lint-backend lint-frontend check-copy

lint-backend:
	cd backend && $(UV) run ruff check . ../scripts
	cd backend && $(UV) run ruff format --check . ../scripts

lint-frontend:
	cd frontend && npm run lint --if-present

format:
	cd backend && $(UV) run ruff check --fix . ../scripts
	cd backend && $(UV) run ruff format . ../scripts

typecheck:
	cd backend && $(UV) run mypy app/core app/engine
	cd frontend && npm run typecheck --if-present

check-copy:
	$(PYTHON) scripts/check_copy.py

openapi-types:
	cd frontend && npx openapi-typescript http://localhost:8000/api/v1/openapi.json -o src/types/api.d.ts
