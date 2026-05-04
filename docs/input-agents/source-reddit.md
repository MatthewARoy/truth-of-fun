# Input Agent Spec: Reddit (r/AskSF, r/bayarea, r/sanfrancisco)

## Source Summary
- Source ID: `reddit`
- Type: Scraper/archive ingest + LLM extraction pipeline
- Strategic role: hyper-local events not present on formal ticketing platforms

## Access and Accounts
- Account type: scraping/archive profile + LLM API account
- API posture: avoid high-cost official mining path unless budget-approved
- Account strategy:
  - maintain separate credentials for content fetch and LLM extraction
  - throttle extraction by batch size and confidence rules

## Ingestion Strategy
- Query-focused retrieval (`weekend events`, `what to do`, `happenings`)
- Extract candidate text from posts/comments
- LLM extraction to structured JSON with strict schema validation
- Relative-date resolution anchored to post timestamp

## Field Mapping
- extracted title -> `title`
- extracted venue/date/time -> `location.*`, `start_time`
- post/subreddit context -> `organizer.name` and source metadata
- mentioned links -> `source.source_url` (or referenced URL in metadata)

## Quality and Risk Controls
- reject low-confidence or hallucinated date mappings
- do not infer private details not present in text
- mark LLM-derived fields with confidence and provenance

## Operational Metrics
- extraction precision/recall sampling score
- invalid-date rejection rate
- event yield per subreddit and keyword cluster
