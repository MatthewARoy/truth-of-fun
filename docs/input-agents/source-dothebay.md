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
- Crawl event listings and event detail pages
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
