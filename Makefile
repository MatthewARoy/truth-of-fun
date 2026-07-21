.PHONY: help db-up db-down migrate seed seed-reset api web worker worker-loop demo install screenshots digest \
        status logs logs-api logs-worker logs-errors

# Where `make status` / `make logs-errors` look for a running API.
API_URL ?= http://127.0.0.1:8000
# How many lines of history the log targets show before following.
LOG_TAIL ?= 200

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
	@echo "  make worker        Run the ingestion pipeline once"
	@echo "  make worker-loop   Run the ingestion worker loop (every 6h)"
	@echo "  make screenshots   Capture UI screenshots into docs/screenshots/"
	@echo "  make digest        Export the events digest markdown for the Life OS weekly weave"
	@echo "                     (requires db-up + migrate + seed/worker to have populated events)"
	@echo ""
	@echo "Operations (see docs/operations.md)"
	@echo "  make status        Ask the running API whether anything is broken"
	@echo "  make logs          Follow logs from all containers"
	@echo "  make logs-api      Follow API logs only"
	@echo "  make logs-worker   Follow ingestion worker logs only"
	@echo "  make logs-errors   Show only warnings and errors across all containers"

install:
	uv sync
	@.venv/bin/playwright install chromium || echo "WARNING: Playwright Chromium install failed — the FuncheapSF and Luma connectors won't run. Retry with: .venv/bin/playwright install chromium"
	npm install
	npm run api-client:build

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
	$(PY) -m app.worker --once

worker-loop:
	$(PY) -m app.worker

demo: db-up migrate seed
	@echo ""
	@echo "Demo data ready. Now start the services in two terminals:"
	@echo "  Terminal A:  make api"
	@echo "  Terminal B:  make web"
	@echo "Then open http://localhost:3000"

screenshots:
	node scripts/capture_screenshots.mjs

# Exports reference/events-digest.md for the Life OS weekly weave. Assumes
# db-up + migrate + seed (or the worker) have already populated events —
# this target does not start Postgres itself.
digest:
	$(PY) scripts/export_digest.py

# --- Operations -------------------------------------------------------------
# See docs/operations.md for what these outputs mean and how to act on them.

# One question: is anything broken? Exits non-zero when the platform is not
# "ok", so it doubles as a deploy smoke test and a cron health check.
status:
	@$(PY) scripts/status.py --api-url $(API_URL)

logs:
	docker compose logs --tail=$(LOG_TAIL) --follow

logs-api:
	docker compose logs --tail=$(LOG_TAIL) --follow api

logs-worker:
	docker compose logs --tail=$(LOG_TAIL) --follow worker

# Containers log JSON (LOG_FORMAT=json in docker-compose.yml), so filter on the
# level field rather than regexing prose. Falls back to a plain grep when the
# line isn't JSON (e.g. Postgres' own output, which isn't ours to format).
logs-errors:
	@docker compose logs --tail=1000 --no-color \
		| grep -Ei '"level": *"(warning|error|critical)"|\b(WARNING|ERROR|CRITICAL)\b' \
		|| echo "No warnings or errors in the last 1000 log lines."
