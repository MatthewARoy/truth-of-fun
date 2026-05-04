# Input Agent Spec: 19hz (Electronic Music Calendar)

## Source Summary
- Source ID: `19hz`
- Type: Scraper (deterministic table parser)
- Strategic role: nightlife/rave coverage with strong niche completeness

## Access and Accounts
- Account type: standard scraper profile (no auth required)
- Auth: public page access
- Account strategy: low-frequency respectful crawling

## Ingestion Strategy
- URL: `https://19hz.info/eventlisting_BayArea.php`
- Parse table rows (`tr`) with stable column semantics
- Time handling:
  - parse start date/time
  - support overnight rollover (`10pm-4am` -> next-day end)
- Title/venue split on ` @ ` convention

## Field Mapping
- row event text -> `title`
- parsed venue token -> `location.venue_name`
- `TBA` venue -> `location.location_is_private=true`
- tag column -> `category_tags`
- row link -> `source.source_url`

## Quality and Risk Controls
- Validate overnight end_time > start_time
- maintain alias mapping for common venue abbreviations
- treat private-location events as valid, not parse failures

## Operational Metrics
- table parse success rate
- count of `location_is_private=true` events
- nightlife event volume by day-of-week
