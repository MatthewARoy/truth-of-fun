.PHONY: help db-up db-down migrate seed seed-reset api web worker demo install screenshots

PY := .venv/bin/python
ALEMBIC := .venv/bin/alembic
UVICORN := .venv/bin/uvicorn

help:
	@echo "Truth of Fun — local commands"
	@echo ""
	@echo "  make install       Install Python + Node deps (uv sync, npm install)"
	@echo "  make db-up         Start Postgres+PostGIS via docker compose"
	@echo "  make db-down       Stop Postgres"
	@echo "  make migrate       Apply database migrations"
	@echo "  make seed          Seed ~40 demo events (idempotent)"
	@echo "  make seed-reset    Wipe events and re-seed"
	@echo "  make demo          db-up + migrate + seed (then start api/web in two terminals)"
	@echo "  make api           Start FastAPI on :8000"
	@echo "  make web           Start Next.js on :3000"
	@echo "  make worker        Run the ingestion worker once"
	@echo "  make screenshots   Capture UI screenshots into docs/screenshots/"

install:
	uv sync
	npm install

db-up:
	docker compose up -d db
	@echo "Waiting for Postgres to be ready..."
	@until docker compose exec -T db pg_isready -U postgres -d truth_of_fun >/dev/null 2>&1; do sleep 1; done
	@echo "Postgres ready on :5433"

db-down:
	docker compose stop db

migrate:
	$(ALEMBIC) upgrade head

seed:
	$(PY) scripts/seed_demo.py

seed-reset:
	$(PY) scripts/seed_demo.py --reset

api:
	$(UVICORN) app.main:app --reload --port 8000

web:
	npm run web:dev

worker:
	$(PY) -m app.worker

demo: db-up migrate seed
	@echo ""
	@echo "Demo data ready. Now start the services in two terminals:"
	@echo "  Terminal A:  make api"
	@echo "  Terminal B:  make web"
	@echo "Then open http://localhost:3000"

screenshots:
	node scripts/capture_screenshots.mjs
