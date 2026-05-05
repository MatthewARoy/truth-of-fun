# Architecture

How Truth of Fun ingests events from heterogeneous sources, deduplicates them, ranks them, and serves them.

## The problem in one paragraph

Event data in any large city is fragmented across roughly three kinds of sources: ticketing infrastructure (Ticketmaster, Eventbrite, Meetup), local curator calendars (FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street Project, Luma), and unstructured social channels (Reddit threads, curated newsletters). Each has different schemas, freshness, completeness, and reliability. The same Friday night concert can appear in three of these — with different titles, slightly different times, and different metadata. A useful product must consolidate them into one feed, deduplicate intelligently, and rank for the individual user.

## Three-tier source taxonomy

| Tier | Examples | Characteristics | Ingestion approach |
| --- | --- | --- | --- |
| **Tier 1 — Infrastructure** | Ticketmaster, Eventbrite, Meetup | Structured schemas, official APIs, rate-limited, high data fidelity. Authoritative for time and venue. | REST/GraphQL clients with token-bucket rate limiting and exponential backoff on 429s. |
| **Tier 2 — Curators** | FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street Project, Luma | Aggregator websites, often no public API. Layout-stable but heterogeneous. Often best signal for "interesting/local". | `httpx` for static pages; Playwright for client-rendered SPAs. Per-source HTML extraction with deterministic selectors. |
| **Tier 3 — Unstructured** | Reddit (r/AskSF, r/sanfrancisco, r/bayarea), curated newsletters (Eddie's List) | Conversational text. No schema. Highest signal-to-noise variance, but highest novelty. | Public JSON endpoints + IMAP for newsletters. LLM extraction to produce structured event records from prose. |

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

1. **Normalize** — coerce types, parse dates into UTC-aware datetimes, validate required fields (title, start_at, location, source).
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
| `start_at` | Earliest observed |
| `end_at` | Latest observed |
| `description`, `venue_name`, `image_url`, `external_url` | Longer non-empty value wins ("richer value") |
| `price` | Lowest (most consumer-friendly) |
| `categories`, `tags` | Set union |
| `status` | Severity-ordered: `scheduled` < `postponed` < `cancelled` < `past` (only escalates) |

This means a Ticketmaster (Tier 1) record's time always wins over a Reddit (Tier 3) record's time, but a longer description scraped from a curator may replace Ticketmaster's terse one.

## Intelligence plane

### Vibe tagging (`app/services/vibe_tagger.py`)

Each event description is passed to Anthropic Claude (Haiku) with a system prompt that asks for 3–5 short, hashtag-prefixed vibe tags (`#Chill`, `#HighEnergy`, `#Date`, `#Tech`, ...). Output is normalized (deduplicated, `#`-prefixed, whitespace-stripped) and capped at 5.

The tagger gracefully degrades: if `ANTHROPIC_API_KEY` is unset or any error occurs, it returns `[]` and the pipeline continues. Tags from the source itself are still preserved.

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

1. Selects an **anchor event** — Tier 1/2 only, within the timeframe window, optionally geo-filtered. First match wins (deterministic).
2. Finds **support events** within a 0.5-mile radius of the anchor (PostGIS `ST_DWithin`).
3. Picks one pre-event (latest available before `anchor.start_at - 30min`) and one post-event (earliest after `anchor.start_at + 30min`).
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

State is exposed at `GET /health/sources` and rendered in the web UI at `/admin/sources` for at-a-glance ops.

## Storage

PostgreSQL 16 + PostGIS. The canonical event model follows [Schema.org/Event](https://schema.org/Event) where practical. Venue locations are `GEOMETRY(POINT, 4326)` so distance/radius queries (used by the concierge and any future map view) are first-class.

## API surface

Routers under `app/api/`:

- `auth` — bcrypt + JWT registration/login
- `discovery` — `GET /events`, `GET /recommendations`, `POST /concierge/itinerary`, onboarding/interest signal capture
- `social` — folders, items, votes, public share tokens
- `health` — `GET /health`, `GET /health/sources`
- `internal_secrets` — AAIM key rotation endpoints (gated by JWT scope)

19 endpoints total. Full request/response shapes in [`api-contract-v1.md`](./api-contract-v1.md).

## What's deliberately not done yet

- **Production deploy automation.** The Dockerfile and `docker-compose.yml` are local-dev oriented. A real deploy needs managed Postgres, secret-management, log shipping, and a real proxy pool for scrapers.
- **CDN / image proxy.** Source-provided image URLs are rendered directly. A production deploy should proxy + cache them.
- **Worker concurrency.** Sources run sequentially within a cycle. Parallelizing is a `asyncio.gather` away but isn't necessary at current scale.
- **Real entity resolution for venues.** The same venue from two sources (e.g., "The Fillmore" vs "Fillmore") is currently treated as two records. A canonical-venue table with fuzzy matching is on the roadmap.
- **Ranking learning loop.** Weights are static. Once we have meaningful click-through data we can move to learned weights or a contextual bandit.
