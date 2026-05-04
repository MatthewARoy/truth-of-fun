# Input Agent Spec: Luma

## Source Summary
- Source ID: `luma`
- Type: Hybrid (internal API preferred, stealth browser fallback)
- Strategic role: SF startup/tech event discovery

## Access and Accounts
- Account type: session/cookie profile, optional API key/header if exposed
- Anti-bot constraints: Cloudflare/Turnstile likelihood
- Account strategy:
  - sticky session for authenticated flows if required
  - rotate fingerprints and proxies for reliability

## Ingestion Strategy
- Preferred: intercept internal JSON/XHR calls and extract structured payloads
- Fallback: Playwright with stealth plugin + infinite scroll loop
- Scope: public event metadata only (exclude private guest-list scraping for MVP)

## Field Mapping
- event JSON/card title -> `title`
- event start/end -> `start_time`/`end_time`
- host/org -> `organizer.name`
- RSVP or interest counts -> `social_signals.attendee_count`
- canonical event URL -> `source.source_url`

## Quality and Risk Controls
- segregate blocked/challenge responses from parser failures
- retain minimal required session artifacts
- compliance guardrail: no private attendee data ingestion

## Operational Metrics
- block/challenge rate
- internal-API hit rate vs DOM fallback rate
- extracted event count and freshness
