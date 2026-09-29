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
- Fallback mode: filtered browse listings over a 14-day window
  (`/d/ca--san-francisco/<slice>/?start_date=…&end_date=…&page=N`)
  - the bare `/d/ca--san-francisco/events/` listing ignores `?page=` (page 2 repeats
    page 1) and 301s a date filter to `/all-events/`, so it cannot be paginated
  - slices, in order: `comedy--events`, `music--events`, `nightlife--events`,
    `food-and-drink--events` (each labels its events with that canonical category),
    then `all-events`; `performing-visual-arts--events` is skipped because it reports
    more events than `all-events` for the same window
  - bounds: stop at the listing's own `page_count` or on a page that adds nothing new;
    at most 5 pages per slice and 25 requests per run, 1 request/second
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
