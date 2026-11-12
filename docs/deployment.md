# Deployment

How to run Truth of Fun in production on a single host, and what each piece
is for. The root `docker-compose.yml` is the **development** stack (published
database port, checked-in password, `APP_ENV=development`); nothing in this
document uses it.

## What gets deployed

```
                    ┌────────────────────── one host ──────────────────────┐
 Internet ──443──▶  │ caddy ──/api/*──▶ api (uvicorn × N) ──▶ db (PostGIS) │
                    │   │                      │                 ▲         │
                    │   └──everything else──▶ web (Next.js)      │         │
                    │                          redis ◀── api     │         │
                    │                  worker (ingestion loop) ──┘         │
                    │                  backup (nightly pg_dump)            │
                    └───────────────────────────────────────────────────────┘
```

| Service | Image | Role |
| --- | --- | --- |
| `caddy` | `caddy:2.10-alpine` | TLS (automatic certificates), HSTS, compression. Serves the web app and the API from **one origin**: `/api/*` is proxied to the API with the prefix stripped. |
| `web` | `apps/web/Dockerfile` | Next.js standalone server. Built with `NEXT_PUBLIC_API_BASE_URL=/api`, so the same image works for any domain and the browser never makes a cross-origin call. |
| `migrate` | root `Dockerfile` (`api` target) | One-shot `alembic upgrade head`. `api` and `worker` start only after it exits 0, so replicas never race through a migration. |
| `api` | root `Dockerfile` (`api` target) | FastAPI. Trusts forwarded headers only from the edge network; rate limits live in Redis so they hold across workers. |
| `worker` | root `Dockerfile` (`worker` target) | Ingestion loop (every 6 h). Holds a database advisory lock per cycle, so a second worker never double-crawls. |
| `db` | `postgis/postgis:16-3.4` | Not published outside the compose network. |
| `redis` | `redis:7-alpine` | Rate-limit windows (and the optional AAIM key inventory). |
| `backup` | `postgis/postgis:16-3.4` | `pg_dump` every 24 h into `deploy/backups/`, 14-day retention. |

## Prerequisites

- A Linux host with Docker Engine and the compose plugin. 2 vCPU / 4 GB RAM is
  a comfortable starting point: the worker's Chromium (FuncheapSF, Luma) is the
  largest consumer.
- A DNS record for your domain pointing at the host; ports 80 and 443 open.
- Secrets for the values marked REQUIRED in `deploy/.env.production.example`.

## First deploy

```bash
git clone https://github.com/MatthewARoy/truth-of-fun.git && cd truth-of-fun
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
$EDITOR deploy/.env.production          # fill in every REQUIRED value

docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml up -d --build
```

Compose refuses to start if a required value is missing — there is no default
password or signing key anywhere in the production stack.

Then verify:

```bash
# Every service healthy (migrate shows "Exited (0)")
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml ps -a

# One-line verdict from your own machine (needs OPS_TOKEN in the environment)
OPS_TOKEN=... make status API_URL=https://<your-domain>/api
```

The first ingestion cycle starts immediately and takes several minutes. Until
it finishes the site is up but empty; `make status` reports
`corpus: no upcoming events` in the meantime.

To shorten the commands below:

```bash
alias tof='docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml'
```

## Upgrades

```bash
git pull
tof up -d --build
```

`migrate` runs first; `api` and `worker` are recreated only once it succeeds.
A failed migration leaves the previous containers serving. Migrations in this
repository are additive unless their docstring says otherwise — read the
docstring of any new file under `alembic/versions/` before upgrading.

**Upgrading across `202611120001`** (adds `events.city` / `events.region`):
the columns start empty and the worker fills them when it starts — seconds
for a typical catalog. Until then region filters fall back to matching the
place name in the venue/address text, so results are present but less precise.

## Rollback

```bash
git checkout <previous-tag-or-commit>
tof up -d --build api web worker
```

Code rolls back freely. The schema does not roll back automatically: an
additive migration is harmless to older code, so leave it applied. Only run
`alembic downgrade` deliberately, after reading the migration's `downgrade()`.

## Backups and restore

`backup` writes `deploy/backups/<db>-<UTC timestamp>.sql.gz` once a day and
deletes dumps older than `BACKUP_KEEP_DAYS`. **These files are on the same disk
as the database.** Copy them off the host on a schedule (object storage,
another machine) — a host failure otherwise takes the backups with it.

Take one on demand (for example before an upgrade):

```bash
tof exec backup bash -c 'pg_dump --no-owner --no-privileges | gzip -9 > /backups/manual-$(date -u +%Y%m%dT%H%M%SZ).sql.gz'
```

Restore into an empty database (this replaces the catalog and all accounts):

```bash
tof stop api worker web
tof exec db bash -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gunzip -c deploy/backups/<file>.sql.gz | tof exec -T db bash -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
tof up -d
```

Rehearse a restore once before you depend on it.

## Operating it

Everything in the [operations runbook](./operations.md) applies; the commands
just go through the production compose file:

```bash
tof logs -f api                 # API (JSON, one object per line)
tof logs -f worker              # ingestion
tof exec worker python -m app.worker --healthcheck
tof exec worker python -m app.worker --once     # refuses if a cycle is already running
```

- **Health.** `GET /api/health/live` and `/api/health/ready` are public probes.
  `/api/health/summary` and `/api/health/sources` (and the `/admin/sources`
  page) need the `X-Ops-Token` header. The AAIM endpoints under
  `/api/internal/*` are not routed from the edge at all.
- **The worker heals itself.** A source that hangs is cancelled after
  `WORKER_SOURCE_TIMEOUT_SECONDS` (20 min) and reported as failing; if the
  whole loop stops making progress for `WORKER_WATCHDOG_SECONDS` (1 h) the
  process exits and Docker restarts it.
- **Alerts.** Set `ALERT_WEBHOOK_URL`; identical alerts are sent at most once
  a day. Set `SENTRY_DSN` to capture API and worker exceptions. Neither
  watches the API's availability from outside — point an external uptime
  monitor at `https://<domain>/api/health/ready` and `https://<domain>/healthz`.
- **Email.** Password-reset mail needs `SMTP_HOST` / `SMTP_FROM`. Without them
  the reset endpoint still answers but nothing is sent (a warning is logged).

## Sizing and limits to know about

- `API_WORKERS` uvicorn processes each keep up to 10 pooled connections
  (+20 overflow). With the worker that stays under Postgres' default
  `max_connections=100` for up to three API workers; raise `max_connections`
  or lower `DB_POOL_SIZE` beyond that.
- The API sets `statement_timeout=15s`. A query that hits it returns an error
  for that request only.
- Public Nominatim allows one request per second **in total per application**
  and requires the contact `GEOCODING_USER_AGENT`. That is enough for the
  default 200 lookups per cycle on one deployment. For more, use a paid
  geocoder or self-host Nominatim — do not run several deployments against the
  public service.
- This is a single-host design. The stateless services (`web`, `api`) can move
  behind a load balancer on more hosts unchanged, since rate limits and
  sessions do not live in process memory; `worker` must stay a singleton in
  spirit (extra copies simply skip cycles while one holds the lock); the
  database is the piece to move to a managed service first.

## Before opening it to the public

Operational:

- [ ] `make status API_URL=https://<domain>/api` reports no `failing` source
      and nothing unexpected. Page-budget notices ("… cap reached; crawl
      incomplete") show as `degraded`; see "Source statuses" in the
      operations runbook.
- [ ] External uptime check on `/api/health/ready` and `/healthz`.
- [ ] `ALERT_WEBHOOK_URL` and `SENTRY_DSN` set, and a test alert seen.
- [ ] Off-host copy of `deploy/backups/` scheduled, and one restore rehearsed.
- [ ] SMTP configured; a password reset completes end to end.
- [ ] Host firewall allows only 80/443 (and SSH from where you administer it).

Decisions only the operator can make (see the review in
[`production-readiness-2026-11-12.md`](./production-readiness-2026-11-12.md)):

- [ ] Each scraped source's terms and `robots.txt` reviewed, and the decision
      recorded per source. FuncheapSF and Luma are fetched with a headless
      browser using stealth settings and DoTheBay with a browser User-Agent;
      decide whether that is acceptable for a public product or whether those
      sources should be licensed, replaced, or switched off.
- [ ] Privacy policy and terms reviewed by counsel (the pages under `/privacy`
      and `/terms` are drafts and say so).
- [ ] Map tile provider terms checked for your traffic (the explore map uses
      CARTO basemaps).
