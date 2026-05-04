# Input Agent Spec: FuncheapSF

## Source Summary
- Source ID: `funcheapsf`
- Type: Scraper (dynamic listing + article parsing)
- Strategic role: free/low-cost local events and neighborhood-level discovery

## Access and Accounts
- Account type: scraper execution profile (proxy + browser fingerprint)
- Auth: generally public pages, no login expected
- Account strategy: rotating residential proxy pool for reliability

## Ingestion Strategy
- Target site: `https://sf.funcheap.com/`
- Use Playwright for lazy loading/infinite scroll pages
- After render completion, parse HTML with deterministic extractors
- LLM assist for listicle/unstructured blocks when deterministic parse confidence is low

## Field Mapping
- post/card title -> `title`
- extracted date/time text -> `start_time`/`end_time`
- venue mentions -> `location.venue_name`
- free indicators -> `offers.is_free=true`
- article URL -> `source.source_url`

## Quality and Risk Controls
- Filter sponsor/advertorial blocks
- Confidence-score extracted entities from unstructured text
- Respect crawl frequency and robots guidance

## Operational Metrics
- lazy-load completion success rate
- structured parse vs LLM-extracted ratio
- free-event coverage trendline
