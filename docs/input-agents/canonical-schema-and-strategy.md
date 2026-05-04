# Canonical Input Schema and Agent Strategy

This document defines the shared contract used by all source input agents.

## 1) Unified Event Record (Canonical)

```json
{
  "event_id": "uuid-or-deterministic-hash",
  "source": {
    "source_id": "ticketmaster|eventbrite|meetup|funcheapsf|19hz|luma|dothebay|sfstation|minnesotastreet|reddit|eddies_list",
    "source_record_id": "string-or-null",
    "source_url": "https://...",
    "ingested_at": "2026-03-01T12:00:00Z",
    "last_seen_at": "2026-03-01T12:00:00Z",
    "capture_mode": "api|scrape|email_ingest|llm_extract",
    "crawl_job_id": "string"
  },
  "title": "string",
  "description": "string-or-null",
  "category_tags": ["music", "nightlife"],
  "vibe_tags": ["HighEnergy", "Social"],
  "status": "scheduled|cancelled|postponed|unknown",
  "timezone": "America/Los_Angeles",
  "start_time": "2026-03-07T03:00:00Z",
  "end_time": "2026-03-07T08:00:00Z",
  "all_day": false,
  "location": {
    "venue_name": "F8",
    "address_line1": "string-or-null",
    "city": "San Francisco",
    "region": "CA",
    "postal_code": "string-or-null",
    "country": "US",
    "lat": 37.0,
    "lon": -122.0,
    "location_is_private": false,
    "location_confidence": 0.94
  },
  "offers": {
    "is_free": false,
    "price_min": 20.0,
    "price_max": 75.0,
    "currency": "USD",
    "price_text": "Starts at $20"
  },
  "organizer": {
    "name": "string-or-null",
    "organizer_url": "https://..."
  },
  "social_signals": {
    "popularity_score": 0.0,
    "vote_count": 0,
    "attendee_count": 0,
    "comment_count": 0
  },
  "media": {
    "image_url": "https://...",
    "thumbnail_url": "https://..."
  },
  "compliance": {
    "retention_policy": "full|metadata_only",
    "tos_risk": "low|medium|high",
    "copyright_risk": "low|medium|high",
    "notes": "string"
  },
  "quality": {
    "record_confidence": 0.0,
    "llm_extracted": false,
    "needs_review": false,
    "validation_errors": []
  }
}
```

## 2) Account and Credential Model

Use one account registry table/collection for all agents:

```json
{
  "account_id": "uuid",
  "source_id": "ticketmaster",
  "account_type": "api_key|oauth|session_cookie|imap|manual",
  "label": "prod-main",
  "status": "active|paused|revoked|expired",
  "secrets_ref": "vault://event-engine/ticketmaster/prod-main",
  "rate_limit_profile": {
    "requests_per_second": 5,
    "requests_per_day": 5000,
    "points_per_window": null,
    "window_seconds": 60
  },
  "session_strategy": "none|refresh_token|cookie_rotation|browser_login",
  "last_validated_at": "2026-03-01T12:00:00Z",
  "owner": "platform-ingestion",
  "notes": "string"
}
```

## 3) Agent Lifecycle
- Discover: fetch candidate records from source endpoint/page/feed
- Extract: parse and convert into source-specific raw model
- Normalize: map into canonical schema
- Validate: schema validation and date/geo sanity checks
- Dedupe: fuzzy merge against existing events
- Persist: upsert canonical records
- Observe: emit source health metrics and alerts

## 4) Common Validation Rules
- Convert all times to UTC, preserve local timezone as metadata
- Reject impossible dates (older than configurable window unless archival mode)
- Require title + start_time for publishable records
- Mark `location_is_private=true` when venue is TBA/private
- Preserve source URL for all published records

## 5) Monitoring Contract (per source)
- `events_ingested_count`
- `events_published_count`
- `parse_error_count`
- `llm_extraction_failures`
- `captcha_or_block_rate`
- `source_latency_p95`
- Alert when daily ingested count drops >20% from 14-day baseline
