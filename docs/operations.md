# Operations runbook

How to tell whether Truth of Fun is healthy, where to look when it isn't, and
what the common failures actually mean.

## The 10-second check

```bash
make status
```

Asks the running API `GET /health/summary` and prints a verdict plus a list of
problems. It exits `0` (ok), `1` (degraded), `2` (failing), or `3` (API
unreachable), so it works as a deploy smoke test or a cron check:

```bash
make status || echo "investigate" | mail -s "Truth of Fun degraded" ops@example.com
```

Point it at a remote deployment with `make status API_URL=https://api.example.com`.

Example output:

```
Truth of Fun: DEGRADED
  database   connected
  sources    11 total (4 degraded, 7 healthy)
  events     1191 upcoming of 1939 total

  5 problem(s):
    - worker: no source has completed a run since 2026-07-16T18:13:24+00:00 — the
      ingestion worker looks stopped (`make worker-loop`, or `docker compose up -d worker`)
    - source luma: degraded — returned 0 events last run
```

## Health endpoints

| Endpoint | Touches DB | Use for |
| --- | --- | --- |
| `GET /health/live` | no | Liveness probe. Only fails if the process is wedged. |
| `GET /health/ready` | yes | Readiness probe. Returns 503 when Postgres is unreachable. |
| `GET /health` | yes | Legacy combined check; the compose healthcheck uses it. |
| `GET /health/sources` | yes | Per-source detail: status, last run, last error. |
| `GET /health/summary` | yes | Everything above rolled into one verdict + problem list. |

Liveness and readiness are deliberately separate: a brief database outage
should take the API *out of the load balancer*, not trigger a restart loop.

## Reading logs

Both the API and the worker log through the same configuration
(`app/core/logging.py`). Format is controlled by `LOG_FORMAT`:

- `text` (default) — human-readable, what `make api` and `make worker` print.
- `json` — one JSON object per line. Containers set this in
  `docker-compose.yml`, so `make logs` output is machine-filterable.

Level is `LOG_LEVEL` (default `INFO`).

```bash
make logs           # follow everything
make logs-api       # API only
make logs-worker    # ingestion worker only
make logs-errors    # only WARNING/ERROR/CRITICAL, across all containers
```

Container logs are capped at 3 × 10MB per service (`x-logging` in
`docker-compose.yml`), so they can't fill the disk. That also means **logs are
not a durable audit trail** — roughly a week of normal traffic. Anything that
must survive longer belongs in the database (which is why source failures are
persisted to `source_health` rather than only logged).

### Tracing one request

Every request gets an `X-Request-ID` (an inbound one is honoured, so a proxy or
client can correlate across hops). It is echoed on the response and stamped on
every log line emitted while handling that request:

```bash
curl -sD- http://localhost:8000/events | grep -i x-request-id
#   x-request-id: 9f2c1ab4e7d03c55

docker compose logs api | grep 9f2c1ab4e7d03c55
```

For a JSON-format log, filter on the field instead:

```bash
docker compose logs --no-color api | jq -c 'select(.request_id == "9f2c1ab4e7d03c55")'
```

### What gets logged at which level

| Level | Emitted for |
| --- | --- |
| `ERROR` | 5xx responses, unhandled exceptions (with traceback), source fetch failures |
| `WARNING` | 4xx responses, requests slower than `LOG_SLOW_REQUEST_MS` (default 1000ms), low API-key quota |
| `INFO` | Normal requests, per-source canary metrics, worker run summaries |
| `CRITICAL` | Canary alert: a source returned 0 events against a historic average > 10 |

Health-probe requests are not logged at INFO — they'd drown everything else —
but they *are* logged when they fail. So `make logs-errors` stays meaningful.

An unhandled exception returns a stable body rather than a bare 500, and the
`request_id` in it is the one to grep for:

```json
{"detail": "Internal server error.", "request_id": "9f2c1ab4e7d03c55"}
```

The exception text is never returned to the caller — only logged.

## Common failures

### `worker: no source has completed a run since …`

The ingestion worker is not running. Every source going stale simultaneously
means one stopped process, not eleven broken scrapers, so the summary reports
it once.

```bash
docker compose ps worker
docker compose up -d worker      # or `make worker-loop` locally
make logs-worker
```

Corpus data keeps serving in the meantime — it just gets progressively more
stale. A source is considered stale after 14 hours (two 6-hour cycles plus
headroom).

### `source X: failing — TimeoutError: …`

That source's `fetch_events` raised. The exception type and message are
persisted to `source_health.last_error` and shown here, so you don't need the
worker logs to know what broke. Common causes:

- **Playwright sources** (`funcheap_sf`, `luma`): site layout changed, or
  Chromium isn't installed — `.venv/bin/playwright install chromium`.
- **`reddit`**: anonymous access is blocked; requires `REDDIT_CLIENT_ID` /
  `REDDIT_CLIENT_SECRET`.
- **`ticketmaster`**: check `TICKETMASTER_API_KEY` and quota — a
  quota warning is logged separately and alerts via webhook.
- **`eddies_list`**: IMAP credentials unset or the mailbox is empty.

A failing status clears itself on the next successful run;
`last_error_at` and `last_success_at` keep the history either way.

### `source X: degraded — returned 0 events last run`

The fetch succeeded but found nothing. Sometimes legitimate (a newsletter with
no new mail), sometimes a silently-changed page structure. Two consecutive zero
runs escalate to `failing`. If the source historically averaged more than 10
events, a `CRITICAL` canary line is logged and an alert webhook fires
(`ALERT_WEBHOOK_URL`).

### `corpus: no upcoming events`

The API is healthy but would render an empty feed — user-visible breakage.
Run `make seed` for demo data, or `make worker` to ingest real data.

### `database: unreachable`

`make status` exits 2 and `/health/ready` returns 503. Check
`docker compose ps db` and `DATABASE_URL`.

## What health endpoints do and don't reveal

`/health/*` is **unauthenticated**. Treat it as public and firewall it if that
is not acceptable — nothing in it is secret by design, but it does describe
your ingestion state.

Exception text is handled carefully because it is where credentials leak:
psycopg2 puts the connection DSN (including the password) in its errors, and
httpx puts the full request URL (including `?apikey=`) in its own.

- Every stored and returned error is passed through a redactor
  (`app/core/redaction.py`) that strips URL credentials, bearer tokens, JWTs,
  labelled secrets, and long opaque values.
- Outside `APP_ENV=development`, the responses carry the exception **type**
  only (`OperationalError`), not the message. Set `EXPOSE_ERROR_DETAIL=true` to
  override — only where the endpoint is not publicly reachable.
- The **full** message is always written to the logs regardless, so nothing is
  lost to the operator.

If a health response is less specific than you need, read the logs for the same
moment: `make logs-errors`.

## Alerting

Set `ALERT_WEBHOOK_URL` to a Slack- or Discord-compatible webhook. The worker
posts to it on canary failures (a source dropping to zero against a healthy
average) and low API-key quota. Delivery failures are logged and never block
the pipeline.

There is no alerting on the API's own error rate yet — that comes from
whatever scrapes `/health/summary`. Wiring `make status` into cron is the
simplest version.

## Before going live

- [ ] `JWT_SECRET_KEY` set (the app refuses to boot without it when `APP_ENV`
      is not `development`).
- [ ] `APP_ENV` set to something other than `development`.
- [ ] `CORS_ALLOWED_ORIGINS` set to the real web origin, not localhost.
- [ ] `ALERT_WEBHOOK_URL` set and tested.
- [ ] `LOG_FORMAT=json` in the deployed environment (already the compose default).
- [ ] `EXPOSE_ERROR_DETAIL` left unset (defaults to false outside development).
- [ ] `/health/*` and `/admin/*` firewalled or fronted by auth — neither has any
      today, and the admin page shows ingestion internals.
- [ ] `make status` returns `ok` against the deployed API.
- [ ] A scheduled `make status` check exists, so a stalled worker is noticed
      without anyone looking.
