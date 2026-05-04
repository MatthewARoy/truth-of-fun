# Input Agent Spec: SF Station

## Source Summary
- Source ID: `sfstation`
- Type: Scraper
- Strategic role: arts + nightlife legacy listings with structured frontend patterns

## Access and Accounts
- Account type: scraper profile
- Auth: public browsing expected
- Account strategy: stable deterministic scraping; moderate crawl rate

## Ingestion Strategy
- Target event listing pages and detail pages
- Leverage likely consistent class structures for location/price/ticket link
- Parse with deterministic selectors first, regex fallback second

## Field Mapping
- title fields -> `title`
- date/time text -> `start_time`/`end_time`
- location/ticket URL -> `location.*` + `source.source_url`
- price fields -> `offers.price_min/max` or `offers.price_text`

## Quality and Risk Controls
- detect template changes with selector health checks
- ensure ticket links remain external deep links
- normalize nightlife category labels for recommendation use

## Operational Metrics
- selector success ratio
- % records with price and ticket-link completeness
- daily arts/nightlife event volume
