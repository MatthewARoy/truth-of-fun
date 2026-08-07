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
| GET | `/recommendations` | user JWT |
| POST | `/users/me/onboarding` | user JWT |
| POST | `/users/me/interests` | user JWT |
| POST | `/concierge/itinerary` | none |
| POST | `/concierge/itinerary/share` | optional |
| GET | `/shared/itineraries/{token}` | none |
| GET | `/folders` | user JWT |
| POST | `/folders` | user JWT |
| GET | `/folders/{folder_id}` | user JWT (owner or member) |
| POST | `/folders/{folder_id}/items` | user JWT (owner) |
| POST | `/folders/{folder_id}/votes` | user JWT (owner or member) |
| POST | `/folders/{folder_id}/invite` | user JWT (owner) |
| POST | `/folders/invites/{invite_token}/accept` | user JWT |
| GET | `/shared/folders/{token}` | none |
| GET | `/health` | none |
| GET | `/health/sources` | none |
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
  "password": "string",
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

Auth: none. Full-text, geo, and preset-filtered event search.

Query parameters:

| Param | Type | Notes |
|---|---|---|
| `q` | string | Full-text search query |
| `lat` | float | Latitude for geo search |
| `lng` | float | Longitude for geo search |
| `radius_miles` | float (> 0) | `lat`, `lng`, `radius_miles` must be provided together (`400` otherwise) |
| `vibe_tag` | string | Filter by vibe tag |
| `time_preset` | `"tonight"` \| `"this_weekend"` | Friendly time window (computed in SF local time) |
| `location_preset` | `"sf"` \| `"oakland"` \| `"san_jose"` | Friendly location filter |
| `start_at` | datetime | Start-time lower bound (overrides preset start) |
| `end_at` | datetime | Start-time upper bound (overrides preset end) |
| `include_past` | bool (default `false`) | Include past events |
| `sort_by` | `"date"` (default) \| `"distance"` | `distance` requires `lat`/`lng` |
| `status` | string | Filter by event status |
| `limit` | int 1–200 (default 25) | |
| `offset` | int ≥ 0 (default 0) | |

Response: `EventResponse[]`.

### GET /recommendations

Auth: user bearer JWT. Personalized upcoming events scored from explicit vibe likes plus decayed behavioral signals. Returns `[]` for users with no preferences or signals.

Query parameters: `limit` (int 1–200, default 25), `offset` (int ≥ 0, default 0).

Response: list of `RecommendationResponse` = `EventResponse` plus:

```json
{
  "match_score": "int",
  "matched_vibes": "string[]"
}
```

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

Auth: none. Parses a natural-language query into an intent/time window, picks an anchor event (source tier ≤ 2), and sequences nearby support events (tier ≥ 3, within 0.5 mi) into an itinerary. `itinerary` is empty (and `anchor_event_id` null) when no anchor matches.

Request:

```json
{
  "query": "string",
  "limit": "int (default 25, clamped to 3–100)"
}
```

Response:

```json
{
  "intent": "string",
  "timeframe": "string",
  "geography": "string | null",
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

Auth: optional (associates the itinerary with the caller when a JWT is present). Freezes an itinerary and returns a public link.

Callers send the stops they are looking at rather than the original query — re-planning server-side could return a different night than the one being shared. Only `kind`, `event_id`, and ordering are taken from the request; every display field is re-read from `events` when the snapshot is written, so a shared page can never render caller-supplied text. `422` if `stops` is empty or longer than 20, `404` if any `event_id` is unknown.

Request:

```json
{
  "query": "string",
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

`stops` holds 1–20 entries. Unauthenticated callers may share, so `query` is capped at 2000 characters.

Response: `PortableItinerary` (below).

### GET /shared/itineraries/{token}

Auth: none — the link is the credential. `404` for an unknown or malformed token.

The stored stops are a snapshot, so the page keeps rendering after the underlying events are re-deduped, repriced, or dropped from the feed. Links are recomputed from the snapshot on every read rather than stored, so improvements to URL building reach itineraries shared before the change.

`PortableItinerary`:

```json
{
  "share_token": "string",
  "share_url": "string (relative, e.g. \"/itinerary/<token>\")",
  "title": "string",
  "query": "string",
  "intent": "string",
  "timeframe": "string",
  "geography": "string | null",
  "anchor_event_id": "int | null",
  "created_at": "datetime",
  "itinerary": ["ItineraryStop"],
  "text": "string"
}
```

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

Auth: none. Liveness probe; runs `SELECT 1` against the database.

Response:

```json
{
  "status": "ok",
  "database": "connected"
}
```

### GET /health/sources

Auth: none. Per-source ingestion health, backed by the database (`source_health` records persisted by the worker), merged with in-process worker state (when fresher) and the source registry. Registered sources that have never run appear with `status: "unknown"`.

Response:

```json
{
  "sources": [
    {
      "name": "string",
      "status": "string (e.g. healthy | degraded | unknown)",
      "last_run_at": "string (ISO 8601) | null",
      "last_event_count": "int | null",
      "consecutive_zeros": "int"
    }
  ]
}
```

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

Scope: `internal:secrets:write`. Reports usage against a leased key and snapshots provider health. `404` for an unknown key, `400` on other store errors.

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

Scope: `internal:secrets:read`. Per-key health for a provider (also persists a usage snapshot).

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
