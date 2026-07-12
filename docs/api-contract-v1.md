# API Contract v1

This contract documents the current web/mobile-facing HTTP API: **20 endpoints** across five routers (`app/api/`). The live OpenAPI schema (`GET /openapi.json`) is the machine-readable source of truth; this document mirrors it.

In the JSON shapes below, values are field types (`int`, `float`, `string`, `bool`, `datetime` = ISO 8601 string), with `| null` marking nullable fields.

## Authentication

| Tier | How | Applies to |
|---|---|---|
| None | — | `/health*`, `/auth/*`, `GET /events`, `POST /concierge/itinerary`, `GET /shared/folders/{token}` |
| User bearer JWT | `Authorization: Bearer <token>` from `/auth/register` or `/auth/login` (HS256, expires per `JWT_EXPIRE_MINUTES`) | `/users/me/*`, `/recommendations`, all `/folders*` except the public share view |
| Internal AAIM JWT | Scoped service JWT (HS256 shared secret or OIDC/JWKS, per `AAIM_JWT_*` / `AAIM_OIDC_*` settings) | `/internal/secrets/*` |

The entire `/internal/secrets/*` tree returns **404** unless `AAIM_ENABLED=true`. When enabled, each endpoint additionally requires the scope listed below (`403` if the token lacks it).

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
| `category` | string | Filter by activity category (e.g. `Fitness`, `Music`). Synonyms like `gym`/`workout`/`yoga` resolve to `Fitness` |
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

`intent` is one of `date_night`, `out_of_town_guests`, `bar_crawl`, `active_day`, `general_night_out`. An `active_day` request (gyms, workout classes, climbing, yoga, run clubs, etc.) sets `category_focus: "Fitness"` and restricts anchor selection to that category.

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
  "category_focus": "string | null",
  "anchor_event_id": "int | null",
  "itinerary": [
    {
      "kind": "string",
      "event_id": "int",
      "title": "string",
      "start_at": "datetime",
      "end_at": "datetime | null",
      "venue_name": "string | null",
      "external_url": "string | null",
      "travel_buffer_minutes_before": "int"
    }
  ]
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
