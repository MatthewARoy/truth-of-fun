# API Contract v1

This contract documents the current web/mobile-facing HTTP API: **22 endpoints** across five routers (`app/api/`). The live OpenAPI schema (`GET /openapi.json`) is the machine-readable source of truth; this document mirrors it.

In the JSON shapes below, values are field types (`int`, `float`, `string`, `bool`, `datetime` = ISO 8601 string), with `| null` marking nullable fields.

## Authentication

| Tier | How | Applies to |
|---|---|---|
| None | — | `/health*`, `/auth/*`, `GET /events`, `POST /concierge/itinerary`, `POST /concierge/itinerary/share`, `GET /shared/folders/{token}`, `GET /shared/itineraries/{token}` |
| User bearer JWT | `Authorization: Bearer <token>` from `/auth/register` or `/auth/login` (HS256, expires per `JWT_EXPIRE_MINUTES`) | `/users/me/*`, `/recommendations`, all `/folders*` except the public share view |
| Internal AAIM JWT | Scoped service JWT (HS256 shared secret or OIDC/JWKS, per `AAIM_JWT_*` / `AAIM_OIDC_*` settings) | `/internal/secrets/*` |

The entire `/internal/secrets/*` tree returns **404** unless `AAIM_ENABLED=true`. When enabled, each endpoint additionally requires the scope listed below (`403` if the token lacks it).

## Rate limits

Abuse-prone endpoints enforce per-client sliding windows and return **429** with a `Retry-After` header (seconds) when exceeded. Limits are tunable via env (`0` disables — see `.env.example`).

| Window | Default | Applies to |
|---|---|---|
| LLM | 30 / hour | `POST /concierge/itinerary`, `POST /users/me/onboarding` |
| Share | 60 / hour | `POST /concierge/itinerary/share` |
| Auth | 20 / 15 min | `POST /auth/login`, `POST /auth/register` (shared window) |

## Endpoint index

| Method | Path | Auth |
|---|---|---|
| POST | `/auth/register` | none |
| POST | `/auth/login` | none |
| GET | `/events` | none |
| GET | `/events/{event_id}` | none |
| GET | `/recommendations` | user JWT |
| PUT | `/users/me/preferences` | user JWT |
| POST | `/users/me/onboarding` | user JWT |
| POST | `/users/me/interests` | user JWT |
| POST | `/concierge/itinerary` | none |
| POST | `/concierge/itinerary/share` | user JWT |
| GET | `/shared/itineraries/{token}` | none |
| GET | `/users/me/itineraries` | user JWT |
| DELETE | `/users/me/itineraries/{token}` | user JWT (owner) |
| GET | `/folders` | user JWT |
| POST | `/folders` | user JWT |
| GET | `/folders/{folder_id}` | user JWT (owner or member) |
| POST | `/folders/{folder_id}/items` | user JWT (owner) |
| POST | `/folders/{folder_id}/votes` | user JWT (owner or member) |
| POST | `/folders/{folder_id}/invite` | user JWT (owner) |
| POST | `/folders/invites/{invite_token}/accept` | user JWT |
| GET | `/shared/folders/{token}` | none |
| GET | `/health` | none |
| GET | `/health/live` | none |
| GET | `/health/ready` | none |
| GET | `/health/sources` | `X-Ops-Token` |
| GET | `/health/summary` | `X-Ops-Token` |
| GET | `/internal/secrets/{provider}/active-key` | AAIM JWT (`internal:secrets:read`) |
| POST | `/internal/secrets/{provider}/usage` | AAIM JWT (`internal:secrets:write`) |
| GET | `/internal/secrets/{provider}/health` | AAIM JWT (`internal:secrets:read`) |

## Auth

### POST /auth/register

Auth: none. Creates a user and returns a token. `201` on success, `409` if the email is taken.

Request:

```json
{
  "email": "string (email)",
  "password": "at least 12 characters; at most 72 UTF-8 bytes",
  "full_name": "string | null (optional)"
}
```

Response (`AuthResponse`, also returned by login):

```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "user_id": "int",
  "email": "string"
}
```

### POST /auth/login

Auth: none. `401` on bad credentials, `403` if the account is deactivated.

Request:

```json
{
  "email": "string (email)",
  "password": "string"
}
```

Response: `AuthResponse` (see above).

## Discovery

### Shared shape: `EventResponse`

Returned by `GET /events` (as a list) and extended by `GET /recommendations`.

```json
{
  "id": "int",
  "title": "string",
  "description": "string | null",
  "start_at": "datetime",
  "end_at": "datetime | null",
  "external_url": "string | null",
  "venue_name": "string | null",
  "tags": "string[]",
  "categories": "string[]",
  "image_url": "string | null",
  "price": "float | null",
  "currency": "string | null",
  "status": "string",
  "people_interested": "int (distinct users with save/click/ticket-click signals; renamed from friends_interested)",
  "distance_miles": "float | null (set only when lat/lng/radius_miles are provided)",
  "lat": "float | null",
  "lng": "float | null",
  "organizer_name": "string | null",
  "attendee_count": "int (default 0)",
  "location_confidence": "float (0–1, default 1.0)",
  "is_free": "bool (default false)"
}
```

### GET /events

Auth: none required; presented PATs require valid events:read delegation (stale user JWTs retain anonymous fallback). Full-text, geo, and preset-filtered event search.

Query parameters:

| Param | Type | Notes |
|---|---|---|
| `q` | string | Full-text search query |
| `lat` | float | Latitude for geo search |
| `lng` | float | Longitude for geo search |
| `radius_miles` | float (> 0) | `lat`, `lng`, `radius_miles` must be provided together (`400` otherwise) |
| `vibe_tag` | string | Filter by vibe tag |
| `category` | string | Filter by activity category (e.g. `Fitness`, `Music`). Synonyms like `gym`/`workout`/`yoga` resolve to `Fitness` |
| `time_preset` | `"tonight"` \| `"this_weekend"` | Friendly time window (computed in SF local time) |
| `location_preset` | `"sf"` \| `"oakland"` \| `"san_jose"` | Friendly location filter |
| `start_at` | datetime | Window lower bound, including ongoing events (overrides preset start) |
| `end_at` | datetime | Start-time upper bound (overrides preset end) |
| `include_past` | bool (default `false`) | Include past events |
| `sort_by` | `"date"` (default) \| `"distance"` | `distance` requires `lat`/`lng` |
| `status` | string | Filter by event status; defaults to scheduled when `include_past=false` |
| `limit` | int 1–200 (default 25) | |
| `offset` | int ≥ 0 (default 0) | |

Response: `EventResponse[]`.

Response headers:

| Header | Notes |
|---|---|
| `X-Total-Count` | Total events matching the filters *before* `limit`/`offset`, so clients know whether to keep paging. |

### GET /events/{event_id}

Auth: none required; presented PATs require valid events:read delegation (stale user JWTs retain anonymous fallback). One event with the provenance needed to cite and qualify it.
Returns `404` when no event has that id.

Response: `EventResponse` plus:

```json
{
  "first_seen_at": "datetime (when this platform first ingested the event — NOT when it was announced)",
  "updated_at": "datetime",
  "source_name": "string (e.g. ticketmaster, funcheap_sf)",
  "source_tier": "int (1 = most trusted)",
  "raw_address": "string | null"
}
```

`first_seen_at` is deliberately not named `created_at`: it records when Truth of
Fun ingested the event, which is not the event's announcement date. Clients must
not present it as one.

### GET /recommendations

Auth: user bearer JWT. Scheduled, upcoming or ongoing events scored from explicit vibe likes plus decayed behavioral signals. Users with no matching preferences/signals receive a popularity, freshness, and diversity fallback. Ranking and diversity are applied in SQL before pagination; only the requested page is hydrated. `match_score` is a heuristic ranking score, not a calibrated match probability.

Query parameters: `limit` (int 1–200, default 25), `offset` (int ≥ 0, default 0).

Response: list of `RecommendationResponse` = `EventResponse` plus:

```json
{
  "match_score": "int",
  "matched_vibes": "string[]"
}
```

### PUT /users/me/preferences

Auth: user bearer JWT. Replaces explicit choices with a canonical list from the supported vibe vocabulary. `[]` clears explicit choices. Unknown tags return `422`. Previous explicit like/onboarding signals are removed; event engagement signals are retained.

Request: `{"preferred_vibes": ["#livemusic", "#art"]}` (at most 50 entries).

Response: `{"user_id": 1, "saved_event_ids": [], "preferred_vibes": ["#livemusic", "#art"]}`.

Use this endpoint for structured pickers; the free-text endpoint below is a separate extraction flow.

### POST /users/me/onboarding

Auth: user bearer JWT. Extracts vibe tags from a free-text prompt and adds them to the user's preferences. `400` if `perfect_saturday` is empty.

Request:

```json
{
  "perfect_saturday": "string (non-empty)"
}
```

Response:

```json
{
  "user_id": "int",
  "extracted_vibes": "string[]",
  "preferred_vibes": "string[]"
}
```

### POST /users/me/interests

Auth: user bearer JWT. Records an engagement signal.

Request:

```json
{
  "action": "\"save\" | \"like\" | \"click\" | \"external_ticket_click\"",
  "event_id": "int | null (required for save/click/external_ticket_click)",
  "vibe_tag": "string | null (required for like; '#' prefix added if missing)"
}
```

`400` if the required field for the action is missing; `404` if `event_id` does not exist.

Response:

```json
{
  "user_id": "int",
  "saved_event_ids": "int[]",
  "preferred_vibes": "string[]"
}
```

### POST /concierge/itinerary

Auth: none required; presented PATs require valid events:read delegation (stale user JWTs retain anonymous fallback). Parses a natural-language query into an intent/time window, picks an anchor event (source tier ≤ 2), and sequences nearby support events (tier ≥ 3, within 0.5 mi) into an itinerary. `itinerary` is empty (and `anchor_event_id` null) when no anchor matches.

`intent` is one of `date_night`, `out_of_town_guests`, `bar_crawl`, `active_day`, `general_night_out`. An `active_day` request (gyms, workout classes, climbing, yoga, run clubs, etc.) sets `category_focus: "Fitness"` and restricts anchor selection to that category.

`limit` is accepted but has no effect. An itinerary is at most three stops by construction, so the field never sized the response; it only ever truncated the candidate pools, which decided the anchor and the post-anchor stop by start time before ranking and sequencing ran.

New stops use `before_event`, `main_event`, and `after_event`; existing shared snapshots retain their old labels. All candidates must be scheduled. Sequencing stays within one outing night and requires a published predecessor end plus a 30-minute travel buffer. Unknown or estimated timing reduces the number of stops. Low-confidence anchor coordinates produce a standalone event instead of an asserted nearby route. The fixed buffer is not a live travel-time estimate.

Request:

```json
{
  "query": "string",
  "limit": "int (accepted for compatibility; ignored — see below)"
}
```

Response:

```json
{
  "intent": "string",
  "timeframe": "string",
  "geography": "string | null",
  "category_focus": "string | null",
  "anchor_event_id": "int | null",
  "title": "string",
  "text": "string",
  "itinerary": ["ItineraryStop"]
}
```

`title` is a subject-line summary (`"Date night in Mission — Sat, Aug 8"`); `text` is the whole plan rendered as pasteable plain text, with times in venue-local time.

`ItineraryStop`:

```json
{
  "kind": "string",
  "event_id": "int",
  "title": "string",
  "start_at": "datetime",
  "end_at": "datetime | null",
  "venue_name": "string | null",
  "address": "string | null",
  "lat": "float | null",
  "lng": "float | null",
  "external_url": "string | null",
  "travel_buffer_minutes_before": "int",
  "links": {
    "tickets_url": "string | null",
    "map_url": "string | null",
    "directions_url": "string | null",
    "food_url": "string | null",
    "drinks_url": "string | null",
    "parking_url": "string | null"
  }
}
```

`links` are Google Maps URLs built from the stop's stored location — no API key and no third-party call. `directions_url` routes from the previous stop, or omits `origin` on the first stop so the map starts from the reader's current location. `food_url` / `drinks_url` / `parking_url` are Maps searches centered on the venue rather than curated picks: the event corpus holds no restaurant, bar, or parking data. Every link is `null` when a stop has no resolvable location. Coordinates below `location_confidence` 0.7 are city-centroid fallbacks and are not used for navigation — those stops route to the venue/address text instead.

### POST /concierge/itinerary/share

Auth: user bearer JWT. Freezes an owned itinerary and returns an expiring public link. Anonymous creation returns `401`; public reading still needs no sign-in. This is an intentional privacy change from the earlier optional-auth contract.

Callers send the selected stops, without the private planning prompt. Event titles, venues, coordinates, and times are re-read from `events`; plan metadata and ordering come from the caller. `422` if `stops` is empty or longer than 20, `404` if any `event_id` is unknown. Creating a link is a separate, explicit publication action; building or copying a plan does not publish it.

Request:

```json
{
  "expires_in_days": "int (1–30, default 14)",
  "intent": "string (default \"general_night_out\")",
  "timeframe": "string (default \"upcoming_week\")",
  "geography": "string | null",
  "anchor_event_id": "int | null",
  "stops": [
    {
      "kind": "string",
      "event_id": "int",
      "travel_buffer_minutes_before": "int (default 0)"
    }
  ]
}
```

`stops` holds 1–20 entries. The legacy `query` input is accepted for compatibility but ignored and not stored on new snapshots. The TypeScript client and MCP sharing tool do not accept it. All sharing and owner-management responses use `Cache-Control: private, no-store`.

Response: `PortableItinerary` (below).

### GET /shared/itineraries/{token}

Auth: none — anyone holding a live link can read the itinerary. Unknown, malformed, expired, and revoked links all return the same `404`. Public responses omit `query` entirely, including snapshots written before this change. Legacy query text may remain in the private database; it is never serialized by these endpoints.

The stored stops are a snapshot, so an active link keeps rendering after the underlying events are re-deduped, repriced, or dropped from the feed. It becomes unavailable at `expires_at` or on owner revocation. Links are recomputed from the snapshot on every read rather than stored. Migration `202609290002` gives existing links a 14-day grace period from migration time and preserves their existing ownership.

`PortableItinerary`:

```json
{
  "share_token": "string",
  "share_url": "string (relative, e.g. \"/itinerary/<token>\")",
  "title": "string",
  "intent": "string",
  "timeframe": "string",
  "geography": "string | null",
  "anchor_event_id": "int | null",
  "created_at": "datetime",
  "expires_at": "datetime",
  "itinerary": ["ItineraryStop"],
  "text": "string"
}
```

### GET /users/me/itineraries

Auth: user bearer JWT. Lists only the caller's published links, newest first.
Accepts `limit` (1–100, default 25) and `offset` (default 0). Includes expired
and revoked links so owners can inspect prior outcomes. Anonymous legacy links
are not assigned to a new owner.

Response: a list of `{share_token, share_url, title, created_at, expires_at,
revoked_at, status}`, where `status` is `active`, `expired`, or `revoked`.
No original prompt is included.

### DELETE /users/me/itineraries/{token}

Auth: user bearer JWT, matching the stored owner. Marks the share revoked and
returns `204` without a body. Repeating the owner's request is idempotent.
Unknown tokens and another user's tokens return the same `404`; knowing a
public token does not grant revocation authority. Revocation prevents future
reads but cannot erase copies a recipient already made.

## Social

### Shared shapes

`FolderResponse`:

```json
{
  "id": "int",
  "name": "string",
  "share_token": "string",
  "created_at": "datetime"
}
```

`FolderDetailResponse` (items sorted by vote score desc, then title):

```json
{
  "id": "int",
  "name": "string",
  "share_token": "string",
  "items": [
    {
      "folder_item_id": "int",
      "event_id": "int",
      "event_title": "string",
      "vote_score": "int (sum of member votes)"
    }
  ]
}
```

### GET /folders

Auth: user bearer JWT. Lists folders the caller owns **or** has joined via an accepted invite, newest-updated first.

Response: `FolderResponse[]`.

### POST /folders

Auth: user bearer JWT. `400` if `name` is blank.

Request:

```json
{
  "name": "string (non-empty)"
}
```

Response: `FolderResponse`.

### GET /folders/{folder_id}

Auth: user bearer JWT — owner or accepted member (`403` otherwise, `404` if missing).

Response: `FolderDetailResponse`.

### POST /folders/{folder_id}/items

Auth: user bearer JWT — owner only. Adding an already-present event is a no-op. `404` if the event does not exist.

Request:

```json
{
  "event_id": "int"
}
```

Response: `FolderDetailResponse`.

### POST /folders/{folder_id}/votes

Auth: user bearer JWT — owner or accepted member. One vote per user per item; revoting replaces the previous value. `vote_value` is normalized to `1` (≥ 1) or `-1` (< 1). `404` if the item is not in this folder.

Request:

```json
{
  "folder_item_id": "int",
  "vote_value": "int (normalized to +1 / -1)"
}
```

Response: `FolderDetailResponse`.

### POST /folders/{folder_id}/invite

Auth: user bearer JWT — owner only. Mints an invite token others can accept to become folder members.

Response:

```json
{
  "folder_id": "int",
  "invite_token": "string",
  "share_url": "string (read-only public path, /shared/folders/{share_token})"
}
```

### POST /folders/invites/{invite_token}/accept

Auth: user bearer JWT. Accepts an active invite and adds the caller as a folder member (idempotent; owners accepting their own invite are a no-op). `404` if the token is unknown or inactive.

Response: `FolderDetailResponse` for the joined folder.

### GET /shared/folders/{token}

Auth: none. Public read-only view by share token. `400` for malformed tokens (< 16 chars or non `[A-Za-z0-9_-]`), `404` if not found.

Response: `FolderDetailResponse`.

## Health

### GET /health

Auth: none. Combined check; runs `SELECT 1` against the database. Retained for
the Docker Compose healthcheck — prefer `/health/live` and `/health/ready`.

Response:

```json
{
  "status": "ok",
  "database": "connected"
}
```

### GET /health/live

Auth: none. Liveness probe. Does **not** touch the database, so a transient
database outage does not cause an orchestrator to restart a healthy process.

Response: `{"status": "ok"}`

### GET /health/ready

Auth: none. Readiness probe. Returns `200` when the database answers, and
`503` (not an exception) with the reason in the body when it does not.

```json
{
  "status": "string (ready | unavailable)",
  "database": "string (connected, or the error type and message)"
}
```

### GET /health/sources

Auth: `X-Ops-Token` header matching `OPS_TOKEN`. Per-source ingestion health, backed by the database (`source_health` records persisted by the worker), merged with in-process worker state (when fresher) and the source registry. Registered sources that have never run appear with `status: "unknown"`.

Response:

```json
{
  "sources": [
    {
      "name": "string",
      "status": "string (healthy | degraded | failing | unknown)",
      "last_run_at": "string (ISO 8601) | null",
      "last_event_count": "int | null",
      "consecutive_zeros": "int",
      "last_error": "string | null (exception type and message from the last failed fetch; cleared on a successful run)",
      "last_error_at": "string (ISO 8601) | null",
      "last_success_at": "string (ISO 8601) | null",
      "is_stale": "bool (no completed run within 14 hours — two ingestion cycles plus headroom)"
    }
  ]
}
```

A source whose fetch raised is reported `failing` immediately, rather than
climbing the consecutive-zero ladder: an exception is a harder signal than a
zero count.

### GET /health/summary

Auth: `X-Ops-Token` header matching `OPS_TOKEN`. Every health signal rolled
into one verdict plus an actionable
problem list — the endpoint to poll when the question is "is anything broken?".
See [the operations runbook](./operations.md).

```json
{
  "status": "string (ok | degraded | failing)",
  "checked_at": "string (ISO 8601)",
  "problems": "string[] (human-readable, each naming its subsystem; empty when status is ok)",
  "database": { "connected": "bool" },
  "sources": {
    "total": "int",
    "by_status": "object (status -> count)",
    "stale": "int",
    "worker_stalled": "bool (every source that has ever run is stale — the worker looks stopped)"
  },
  "events": {
    "total_events": "int",
    "upcoming_events": "int",
    "newest_event_first_seen_at": "string (ISO 8601) | null"
  }
}
```

When `worker_stalled` is true, the per-source staleness entries are collapsed
into a single `worker:` problem: every source going stale at once means one
stopped process, not eleven broken scrapers.

## Internal secrets (AAIM)

Key-rotation endpoints for the AAIM subsystem. All three return **404** unless `AAIM_ENABLED=true`; when enabled they require an internal AAIM JWT carrying the listed scope (`401` missing/invalid token, `403` missing scope). `{provider}` is normalized to lowercase (e.g. `ticketmaster`).

### GET /internal/secrets/{provider}/active-key

Scope: `internal:secrets:read`. Leases the least-used active key for the provider. `404` if no key is available.

Response:

```json
{
  "provider": "string",
  "key_id": "string",
  "api_key": "string (raw provider key)",
  "usage_count": "int",
  "quota_limit": "int",
  "status": "string",
  "source": "string (e.g. redis | env)"
}
```

### POST /internal/secrets/{provider}/usage

Scope: `internal:secrets:write`. Reports usage against a leased key and samples that key's health at most hourly or on a state change. Sampling is best effort and skips a busy sampler. Snapshots retain at most 30 days and 1,000 rows per key. `404` for an unknown key, `400` on store errors before usage is accepted.

Request:

```json
{
  "key_id": "string",
  "calls": "int (default 1, 0–10000)",
  "last_status": "int | null",
  "last_error": "string | null (max 1024 chars)",
  "disable": "bool (default false)"
}
```

Response:

```json
{
  "provider": "string",
  "key_id": "string",
  "updated": "bool"
}
```

### GET /internal/secrets/{provider}/health

Scope: `internal:secrets:read`. Read-only per-key health for a provider.

Response:

```json
{
  "provider": "string",
  "total_keys": "int",
  "active_keys": "int",
  "exhausted_keys": "int",
  "disabled_keys": "int",
  "keys": [
    {
      "key_id": "string",
      "usage_count": "int",
      "quota_limit": "int",
      "status": "string (active | exhausted | disabled)",
      "last_status": "int | null",
      "last_error": "string | null",
      "updated_at_epoch": "int"
    }
  ]
}
```

## Notes

- All authenticated user endpoints expect `Authorization: Bearer <JWT>` issued by `/auth/register` or `/auth/login`.
- Validation failures on typed parameters/bodies return FastAPI's standard `422` shape (`{"detail": [...]}`).
- Contract changes should be additive while web and mobile clients are bootstrapping.

## Scoped agent access (additive, 2026-09-29)

`POST /users/me/tokens` (201) accepts `name` (1–100 plain characters), nonempty
`scopes` drawn from `events:read`, `profile:read`, `signals:write`, `plans:read`,
and `expires_in_days` (1–365, default 30). Owner user JWT required; PATs cannot
manage tokens. At most 50 active tokens per owner. Response includes id, name,
prefix, scopes, created/expiry/revocation/last-used timestamps, request_count,
and a one-time `token` secret. Only the hash persists.

`GET /users/me/tokens?limit=50&offset=0` returns owned metadata including revoked
and expired tokens, newest first (limit max 100); neither hash nor raw secret
is returned. `DELETE /users/me/tokens/{token_id}` idempotently revokes an owned
token (204), with 404 for unknown or cross-owner ids. These routes and the new
`GET /users/me` profile response use `Cache-Control: private, no-store`.

Bearer `tof_pat_<12 hex prefix>_<43 character secret>` is accepted by scoped
routes through `Actor`. Missing scope returns 403, invalid/expired/revoked token
401, inactive owner 403. JWT users retain interactive authority. Public event
read routes remain anonymous when no token is presented; a presented PAT must
be valid and have events:read. Profile reads require profile:read;
recommendations need both profile:read and events:read. Signal writes require
signals:write and profile:read, retaining `created_via=agent:{token_id}` on each
signal (human writes `user`; pre-migration/old-process writes `legacy`). Events-only planning omits personal
ranking inputs. Own itinerary-link listing supports plans:read. Token/credential
management, public publication/revocation, onboarding/preferences and folder
access remain user-JWT-only. Future scopes are rejected until implemented.

`GET /users/me` returns user_id, preferred_vibes, saved_event_ids and learned
vibe_scores. Password hashes and email are omitted. The MCP get_my_profile tool
wraps this route; TOF_TOKEN supports PATs without password exchange.

Usage admission atomically rechecks expiry/revocation and increments request_count
and last_used_at. Count includes successfully authenticated admissions even when
a route subsequently denies scope or fails, not anonymous traffic. Revocation
prevents new admissions; in-flight work may complete. PAT requests have a 120/min
per-token cap per API replica. Existing auth/LLM/share IP caps remain enforced.

Migration `202609290004` creates agent_tokens and adds user_signals.created_via
with database default `legacy`, preserving existing rows and foreign keys. Apply via normal
release procedures before serving new code; this task validates only disposable
databases. Downgrade removes agent credentials/provenance but retains user/event
and signal rows. Credential rotation/recovery for existing JWTs is separate work.
