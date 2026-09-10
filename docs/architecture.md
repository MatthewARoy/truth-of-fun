# Architecture

How Truth of Fun ingests events from heterogeneous sources, deduplicates them, ranks them, and serves them.

## The problem in one paragraph

Event data in any large city is fragmented across roughly three kinds of sources: ticketing infrastructure (Ticketmaster, Eventbrite, Meetup), local curator calendars (FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street Project, Luma), and unstructured social channels (Reddit threads, curated newsletters). Each has different schemas, freshness, completeness, and reliability. The same Friday night concert can appear in three of these — with different titles, slightly different times, and different metadata. A useful product must consolidate them into one feed, deduplicate intelligently, and rank for the individual user.

## Three-tier source taxonomy

| Tier | Examples | Characteristics | Ingestion approach |
| --- | --- | --- | --- |
| **Tier 1 — Infrastructure** | Ticketmaster, Eventbrite (public listing scrape), Meetup | Structured schemas, rate-limited, high data fidelity. Authoritative for time and venue. | REST/GraphQL clients with sliding-window rate limiting and exponential backoff on 429/5xx. |
| **Tier 2 — Curators** | FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street Project, Luma | Aggregator websites, often no public API. Layout-stable but heterogeneous. Often best signal for "interesting/local". | `httpx` for static pages; Playwright for client-rendered SPAs. Per-source HTML extraction with deterministic selectors. |
| **Tier 3 — Unstructured** | Reddit (r/AskSF, r/sanfrancisco, r/bayarea), curated newsletters (Eddie's List) | Conversational text. No schema. Highest signal-to-noise variance, but highest novelty. | Public JSON endpoints + IMAP for newsletters. LLM extraction to produce structured event records from prose (deterministic heuristic fallback when no `ANTHROPIC_API_KEY` is configured). |

The tier classification matters at merge time (see "Trust hierarchy" below).

## Pipeline

```
Sources → Ingestion worker → Pipeline (dedupe + LLM tag) → Postgres → API → UI
                  ↓
        Canary alerting + health state machine
```

### Ingestion worker

A long-running async process (`app/worker.py`) that:

1. Iterates the source registry every `WORKER_INTERVAL_SECONDS` (default 6 hours).
2. Calls each source's `fetch_events()` independently (failure of one source never blocks others).
3. Records per-source health metrics (see below).
4. Hands the union of raw payloads to the data pipeline.
5. Marks events that ended more than 24 hours ago as `past`.

### Data pipeline (`app/services/data_pipeline.py`)

For each batch of raw events:

1. **Normalize** — coerce types, parse dates into UTC-aware datetimes, validate required fields (title, start_at, location, source), and infer canonical activity categories (`app/services/categories.py`). Inference is additive: source category strings are preserved, and buckets implied by keywords in the title/description are appended — e.g. an untagged "gym promo — first month free" gains `Fitness`. This lets participatory/active offers (gyms, workout classes, climbing, yoga, run clubs) surface alongside shows and festivals without every source tagging them.
2. **In-batch dedupe** — collapse duplicates *within* the batch before touching the database.
3. **Cross-batch dedupe** — for each candidate, look up any existing event in a ±2-hour window and apply the same-event heuristic.
4. **LLM enrichment** — pass the description through the vibe tagger to get 3–5 hashtag-style vibe tags.
5. **Insert or merge** — new events are inserted; matched events are merged via the trust hierarchy.

### Same-event heuristic

Two events are considered the same iff:

- Their `start_at` differs by **≤ 2 hours**, AND
- `fuzz.ratio(title_a, title_b) > 85` (Levenshtein, normalized to 0–100)

These thresholds were chosen empirically. Stricter values (e.g., 90% similarity, ±1 hour) cause false negatives on title variations like *"Phoebe Bridgers"* vs *"Phoebe Bridgers — Reunion Tour"*. Looser values cause false positives across two genuinely different events at the same venue an hour apart.

### Trust hierarchy

When merging, we prefer:

| Field | Rule |
| --- | --- |
| `source_tier` | Lower (more authoritative) wins |
| `start_at` / `end_at` | Taken from the more authoritative (lower-tier) source; between equal tiers, earliest start and latest end |
| `description`, `venue_name`, `image_url`, `external_url` | Longer non-empty value wins ("richer value") |
| `price` | Lowest (most consumer-friendly) |
| `categories`, `tags` | Set union |
| `status` | Severity-ordered: `scheduled` < `postponed` < `cancelled` < `past` (only escalates) |

This means a Ticketmaster (Tier 1) record's time always wins over a Reddit (Tier 3) record's time, but a longer description scraped from a curator may replace Ticketmaster's terse one.

## Intelligence plane

### Vibe tagging (`app/services/vibe_tagger.py`)

Each event description is passed to Anthropic Claude (Haiku) with a system prompt that asks for 3–5 short, hashtag-prefixed vibe tags (`#Chill`, `#HighEnergy`, `#Date`, `#Tech`, ...). Output is normalized (deduplicated, `#`-prefixed, whitespace-stripped) and capped at 5.

The tagger gracefully degrades: if `ANTHROPIC_API_KEY` is unset or any error occurs, it returns `[]` and the pipeline continues. Tags from the source itself are still preserved.

### Venue geocoding (`app/services/geocoding.py`)

Events carry a `location_confidence`, and radius search drops anything below `0.5` — so a venue the pipeline cannot place is invisible to every distance query, not merely imprecise.

Resolution runs in two passes:

1. **Static table** (`app/ingestion/venue_cache.py`) — a hand-verified dict of Bay Area venues. Offline, exact, and scored `0.9`. Sources apply it while normalizing.
2. **Geocoding provider** — consulted only on a miss, from `DataPipelineService.enrich_locations` before the upsert. Queries are tried most-specific first: `raw_address`, then the venue name qualified with its city, then any street address embedded in either (`"Local Economy, 6028 College Ave, Oakland"` resolves to nothing; the address inside it resolves to a building).

Confidence comes from the provider's own precision signal rather than a constant. Nominatim's `place_rank` maps to `poi` → `0.85`, `street` → `0.7`, and anything coarser to `area` → `0.4`. That last case is deliberate: a result that only resolves to a city *is* the centroid fallback the row already has, so it stays under the radius threshold instead of pushing a guess through it. Nothing geocoded ever outranks the hand-verified table.

Two guards protect against the failure that matters more than a miss — a confident coordinate in the wrong place. The request is hard-bounded to a Northern California viewbox, and the response coordinate is re-checked against the same box.

A venue name that is a placeholder — `TBA`, `Secret Location`, `Private Residence`, `Online` — is never geocoded, qualified or not (19hz writes `TBA (San Jose)`). Observed on real data: geocoding `TBA` returned a POI near Merced at `0.85`, which is an event with no known location acquiring a confident, fabricated one. Only a `raw_address` alongside the placeholder is treated as real.

Known limitation: the provider is asked for a single best match, so an ambiguous chain name (`Dave & Buster's`, with several Bay Area locations) can resolve to the wrong branch. The bounding box catches the wrong *region*, not the wrong branch within it; a `raw_address` is what disambiguates, which is why it leads the query order.

Everything degrades to the previous behaviour. `GEOCODING_PROVIDER` unset means the static table only; an unrecognised value logs a warning and disables geocoding rather than failing the run; and an unreachable provider, a 429, or any exception leaves the event on its city centroid and the cycle completes.

Provider answers — successes *and* failures — are cached in the `geocode_cache` table. The worker re-reads every feed every six hours and Nominatim permits one request per second, so negative caching is what keeps the long tail of names that will never resolve from consuming the whole budget every cycle. Failure rows expire after `GEOCODING_FAILURE_RETRY_DAYS`.

The ingestion hook only reaches events a source re-emits. For events already stored on a centroid whose listing has rolled off its feed, `python -m scripts.backfill_geocode` (dry-run by default, `--apply` to write) resolves them using the same geocoder, cache and write rule.

### Concierge intent parsing (`app/services/concierge.py`)

Natural-language requests like *"Plan a date night in the Mission Saturday"* are parsed by Claude into a structured JSON schema:

```json
{
  "intent": "date_night | out_of_town_guests | bar_crawl | general_night_out",
  "geography": "<neighborhood string or null>",
  "timeframe": "tonight | tomorrow | this_saturday | this_weekend | upcoming_week"
}
```

If the LLM call fails or no API key is configured, the request falls back to a deterministic keyword parser. The downstream itinerary builder doesn't know which path was taken.

### Itinerary sequencing

Given a parsed intent, the concierge:

1. Selects an **anchor event** — Tier 1/2 only, within the timeframe window, optionally geo-filtered, and (for evening intents) starting in that intent's local hour range — falling back to the whole window when that range turns up nothing, rather than returning an empty night. Every candidate is then ranked by the intent's vibe profile plus the caller's own profile, and the top-scoring one anchors the night.
2. Finds **support events** within a 0.5-mile radius of the anchor (PostGIS `ST_DWithin`), widening to 1 mile only if that comes back empty.
3. Picks one pre-event (latest available before `anchor.start_at - 30min`) and one post-event (earliest after `anchor.start_at + 30min`). Both queries above are bounded by the window and the radius alone — never by a row limit, which would decide the night by start time before ranking and bracketing ever ran.
4. Inserts 30-minute travel buffers between stops.

The output is a `[pre_event_drink → main_event → late_night_snack]` sequence with explicit travel buffers.

## Recommender (`app/services/recommender.py`)

A weighted multi-signal score, normalized to 0–100:

| Component | Weight | What it measures |
| --- | --- | --- |
| **Vibe match** | 50% | Overlap between event tags and (a) the user's explicit `preferred_vibes`, (b) decayed behavioral signals (saves, clicks, ticket-clicks). |
| **Popularity** | 25% | Distinct user count for `save` / `click` / `external_ticket_click` signals. Capped at 10 to avoid runaway. |
| **Freshness** | 15% | Stepwise: 100 if `created_at < 24h`, 75 if `< 48h`, 50 if `< 7d`, else 25. |
| **Diversity** | 10% | Penalizes consecutive events sharing the same primary category by −10. |

Behavioral signals decay with a **30-day half-life**: a save 30 days ago counts half as much as one yesterday. Implementation lives in `app/services/user_profile.py`.

## Resilience: canary metrics + health state machine

Scrapers break silently when sites change. The worker mitigates this with:

- **Per-source rolling history** — last N event counts kept in a deque (default `N=5`).
- **Canary alert** — if `historic_avg > 10` and `current_count == 0`, emit a critical log + queue an alert webhook.
- **State machine** — each source transitions:
  - `healthy` (current run > 0)
  - `degraded` (1 consecutive zero)
  - `failing` (≥ 2 consecutive zeros)

After each run the worker persists per-source health to the `source_health` table, so the API process (a separate process in the normal deployment) serves real state at `GET /health/sources`, rendered in the web UI at `/admin/sources` for at-a-glance ops.

## Storage

PostgreSQL 16 + PostGIS. The canonical event model follows [Schema.org/Event](https://schema.org/Event) where practical. Venue locations are `GEOMETRY(POINT, 4326)` so distance/radius queries (used by the concierge and any future map view) are first-class.

## API surface

Routers under `app/api/`:

- `auth` — bcrypt + JWT registration/login
- `discovery` — `GET /events`, `GET /recommendations`, `POST /concierge/itinerary`, onboarding/interest signal capture
- `social` — folders, items, votes, public share tokens
- `health` — `GET /health`, `GET /health/sources`
- `internal_secrets` — AAIM (API-key Acquisition & Inventory Management, the internal key-rotation subsystem — see below) endpoints (404 unless `AAIM_ENABLED=true`; then gated by JWT scope)

20 endpoints total. Full request/response shapes in [`api-contract-v1.md`](./api-contract-v1.md).

## Enabling AAIM key rotation

AAIM (API-key Acquisition & Inventory Management) is the internal subsystem that rotates provider API keys (currently Ticketmaster) through a Redis-backed store (`app/services/secrets_store.py`) with least-used selection and quota tracking. It is **disabled by default** (`AAIM_ENABLED=false`); with `AAIM_FALLBACK_TO_ENV=true` the stack simply uses plain env vars like `TICKETMASTER_API_KEY`, which is the right setup for local and OSS use.

To actually turn rotation on:

1. **Start Redis.** `docker-compose.yml` ships an optional service behind a profile:

   ```bash
   docker compose --profile aaim up -d redis
   ```

2. **Configure the app.** Set `AAIM_ENABLED=true` and point `REDIS_URL` at the instance (`redis://127.0.0.1:6379/0` from the host, `redis://redis:6379/0` from inside compose), then restart the api/worker — the store handle is cached per process, so processes started while Redis was down keep the env-fallback store until restarted.

3. **Seed keys.** The store reads two Redis structures per provider (key prefix defaults to `aaim`, configurable via `AAIM_REDIS_PREFIX`):

   - `aaim:keys:<provider>:ids` — a SET of key ids for the provider
   - `aaim:keys:<provider>:<key_id>` — a HASH with fields `api_key`, `usage_count`, `quota_limit`, `status` (`active` / `disabled` / `exhausted`), `last_status`, `last_error`, `updated_at_epoch`

   Seed a Ticketmaster key with `redis-cli`:

   ```bash
   redis-cli SADD aaim:keys:ticketmaster:ids primary
   redis-cli HSET aaim:keys:ticketmaster:primary \
     api_key YOUR_TICKETMASTER_KEY usage_count 0 quota_limit 10000 \
     status active last_status "" last_error "" updated_at_epoch "$(date +%s)"
   ```

   On each fetch the Ticketmaster connector leases the active, under-quota key with the lowest `usage_count` and reports usage back; a key flips to `exhausted` at its quota and rotation moves to the next id in the set.

   Quotas are rate windows, so exhausted keys recover automatically: at the start of every worker run, keys that have been `exhausted` for at least `AAIM_QUOTA_WINDOW_HOURS` (default `24`) have their `usage_count` cleared and `status` reset to `active`. Set `AAIM_QUOTA_WINDOW_HOURS=0` to disable auto-reset and recover keys manually instead. Deliberately `disabled` keys are never auto-reactivated.

The worker and connectors need only `AAIM_ENABLED` + `REDIS_URL`. The `internal_secrets` HTTP endpoints additionally require the `AAIM_OIDC_*` / `AAIM_JWT_*` settings to authenticate callers.

## What's deliberately not done yet

- **Production deploy automation.** The Dockerfile and `docker-compose.yml` are local-dev oriented. A real deploy needs managed Postgres, secret-management, log shipping, and a real proxy pool for scrapers.
- **CDN / image proxy.** Source-provided image URLs are rendered directly. A production deploy should proxy + cache them.
- **Worker concurrency.** Sources run sequentially within a cycle. Parallelizing is a `asyncio.gather` away but isn't necessary at current scale.
- **Real entity resolution for venues.** The same venue from two sources (e.g., "The Fillmore" vs "Fillmore") is currently treated as two records. A canonical-venue table with fuzzy matching is on the roadmap.
- **Ranking learning loop.** Weights are static. Once we have meaningful click-through data we can move to learned weights or a contextual bandit.
