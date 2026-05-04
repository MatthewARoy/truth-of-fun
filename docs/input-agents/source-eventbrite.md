# Input Agent Spec: Eventbrite (API + Fallback Scraper)

## Source Summary
- Source ID: `eventbrite`
- Type: Hybrid (API preferred, scraper fallback)
- Strategic role: high-volume creator-economy events (classes, workshops, indie)

## Access and Accounts
- Account type: partner API token where available
- Fallback account type: scraper session (if allowed)
- Compliance posture:
  - use metadata-only retention when sourced via scraping
  - preserve source attribution and link-out

## Ingestion Strategy
- Primary mode: partner/API ingestion for permitted scopes
- Fallback mode: listing-page scrape (`/d/ca--san-francisco/events/`)
- Parser rules:
  - robust date parsing from formatted strings
  - price text normalization (`Free`, `Starts at $X`)
  - capture listing URL and organizer when available

## Field Mapping
- card title -> `title`
- card datetime text -> `start_time`
- location snippet -> `location.venue_name` / address fields
- price text -> `offers.price_text` + parsed numeric fields
- listing URL -> `source.source_url`

## Quality and Risk Controls
- Mark scrape-derived descriptions/images with short retention
- Do not rely on source ranking for completeness
- Enforce source-specific dedupe with Ticketmaster/DoTheBay overlaps

## Operational Metrics
- API coverage vs scraper coverage ratio
- parse success rate for date/price fields
- compliance flags raised per crawl
