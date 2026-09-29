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
- Crawl the dated day calendars `/calendar/bay-area/MM-DD-YYYY` for the next 7 days,
  following `rel="next"` (at most 4 pages a day); the undated `/calendar/bay-area`
  only previews six events per day
- Also read `/comedy/calendar/MM-DD-YYYY` (at most 2 pages a day) to record SF Station's
  own Comedy category, which the general listing does not show
- Bounds: 45 requests and 800 events per run, 1 request/second
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
