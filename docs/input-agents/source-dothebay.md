# Input Agent Spec: DoTheBay

## Source Summary
- Source ID: `dothebay`
- Type: Scraper
- Strategic role: lifestyle curation and popularity signal extraction

## Access and Accounts
- Account type: scraper profile
- Auth: public pages
- Account strategy: standard proxy rotation; avoid aggressive crawl cadence

## Ingestion Strategy
- Crawl the dated day pages `/events/YYYY/M/D` for the next 7 days, following
  `rel="next"` (at most 3 pages a day, 21 requests per run, 1 request/second);
  `/events` alone shows only today
- Map each card's own `ds-event-category-*` class onto canonical categories; slugs
  without a clear canonical home (dance, variety, shopping) are not guessed
- Extract popularity/vote indicators (e.g., editorial picks / vote count)
- Filter sponsorship modules and promoted placements from event body text

## Field Mapping
- listing/event title -> `title`
- datetime fields -> `start_time`/`end_time`
- venue/address -> `location.*`
- vote/popularity -> `social_signals.vote_count` + normalized `popularity_score`
- event URL -> `source.source_url`

## Quality and Risk Controls
- distinguish editorial events from paid promotions
- maintain parser selectors for popularity fields with fallback logic
- dedupe heavily against Ticketmaster overlap

## Operational Metrics
- popularity field extraction coverage
- sponsorship-content filter rate
- valid event publish count
