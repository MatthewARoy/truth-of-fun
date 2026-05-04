# Input Agent Spec: Minnesota Street Project + Arts Venues

## Source Summary
- Source ID: `minnesotastreet` (extendable to additional arts venues)
- Type: Scraper (calendar + exhibition pages)
- Strategic role: gallery/exhibition coverage and opening-reception events

## Access and Accounts
- Account type: scraper profile
- Auth: public pages
- Account strategy: low-frequency crawl with careful date-range parsing

## Ingestion Strategy
- Ingest event listing and exhibition detail pages
- Core requirement: differentiate long-running exhibitions vs point-in-time receptions
- Create event typing field in normalized output:
  - `event_kind=exhibition_window`
  - `event_kind=opening_reception`

## Field Mapping
- exhibition title -> `title`
- date range -> `start_time` + `end_time` with `all_day=true` where appropriate
- reception date/time -> point-in-time event fields
- venue/gallery location -> `location.*`
- detail URL -> `source.source_url`

## Quality and Risk Controls
- prevent daily feed clutter from long-running exhibitions
- apply dedupe only within matching `event_kind`
- keep gallery attribution in `organizer.name`

## Operational Metrics
- ratio of exhibition windows vs receptions
- correctness checks for date-range parsing
- arts event freshness and coverage
