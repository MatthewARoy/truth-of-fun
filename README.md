# Truth of Fun

A multi-source event aggregation and recommendation engine. Pulls events from official ticketing APIs, public calendars, and community sources into a single, deduplicated, geospatially searchable feed — with a recommendation layer that learns from user signals.

> The reference deployment is configured for the SF Bay Area (Ticketmaster DMA 382, local calendars like FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street Project, and r/AskSF/r/sanfrancisco/r/bayarea). Sources are modular — swap in agents for other regions by editing `app/ingestion/sources/`.

## Features

- **Hybrid ingestion** — REST/GraphQL APIs (Ticketmaster, Meetup) plus Playwright-stealth scrapers and IMAP newsletter parsing
- **Schema.org/Event canonical model** with PostGIS geometry for venues
- **Deduplication** with fuzzy title match + time-window heuristics; tier-based source preference
- **Vibe tagging** via LLM (Anthropic Claude) for unstructured event text
- **Recommendations** with weighted user signals and 30-day half-life decay
- **Concierge mode** — natural-language intent → itinerary with travel buffers
- **Social** — shared shortlist folders, soft-RSVP votes, public share links
- **Web UI** — Next.js 15 / React 19 / Tailwind frontend

## Tech stack

- **Backend:** FastAPI (Python 3.11), SQLModel, PostgreSQL 16 + PostGIS, Alembic, Redis (optional, for AAIM secrets store)
- **Frontend:** Next.js (App Router), TypeScript, Tailwind, Playwright for E2E
- **Ingestion:** httpx, Playwright-stealth, anthropic SDK
- **Auth:** bcrypt + JWT for end users; optional AAIM (OIDC/JWKS) for internal service-to-service

## Repository layout

```
app/                  FastAPI backend
  api/                Routers: auth, discovery, social, health, internal_secrets
  services/           Business logic: recommender, concierge, vibe tagger, data pipeline
  ingestion/          Source connectors and scrapers
  models/             SQLModel ORM models
  core/               Config and security
alembic/              Database migrations
apps/web/             Next.js frontend
apps/mobile/          (placeholder for future mobile client)
packages/api-client/  Shared TypeScript client + types
docs/                 Public architecture and contract docs
tests/                pytest suite
```

## Quick start

### Prerequisites

- Python 3.11
- Node.js 20+
- Docker (for Postgres+PostGIS and optional Redis)

### Backend

```bash
cp .env.example .env
# Edit .env and add at minimum a TICKETMASTER_API_KEY (optional) and a real JWT_SECRET_KEY for non-dev use
docker compose up -d db
uv sync                       # or: pip install -e .
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

API will be on `http://127.0.0.1:8000` — Swagger UI at `/docs`.

### Web

```bash
cp apps/web/.env.local.example apps/web/.env.local
npm install
npm run web:dev
```

Web UI on `http://localhost:3000`.

### Worker (background ingestion)

```bash
.venv/bin/python -m app.worker
```

Or: `docker compose up -d` to bring up `db`, `api`, and `worker` together.

## Configuration

All runtime config is read from environment variables — see [`.env.example`](./.env.example) for the full set. Key ones:

| Variable | Required? | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | Postgres + PostGIS DSN |
| `JWT_SECRET_KEY` | yes for non-dev | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Startup will refuse to boot in non-`development` `APP_ENV` if unset. |
| `TICKETMASTER_API_KEY` | optional | Disables Ticketmaster ingestion if blank |
| `ANTHROPIC_API_KEY` | optional | Disables vibe tagging if blank |
| `REDIS_URL` | optional | Required if `AAIM_ENABLED=true` |
| `PROXY_URL` / `PROXY_ROTATION` | optional | For scrapers behind aggressive bot protection |

## Documentation

- [API contract (v1)](./docs/api-contract-v1.md)
- [Frontend architecture](./docs/frontend-architecture.md)
- [Input agents — per-source ingestion specs](./docs/input-agents/README.md)
- [Integration testability matrix](./docs/INTEGRATIONS.md)

## Testing

```bash
.venv/bin/pytest                   # backend
npm run web:lint                   # web lint
npm run web:typecheck              # web typecheck
npm run web:test                   # web E2E (Playwright)
```

## Responsible-use notes

This project includes web scrapers for public event calendars. When deploying:

- Honor `robots.txt` and Terms of Service for each source.
- Set conservative rate limits and a descriptive `User-Agent`.
- Prefer official APIs when available.
- Do not republish copyrighted descriptions or images without permission — link back to the original source.

## License

[MIT](./LICENSE) © 2026 Matthew Roy
