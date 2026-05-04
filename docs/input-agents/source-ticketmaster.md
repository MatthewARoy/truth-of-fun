# Input Agent Spec: Ticketmaster Discovery API

## Source Summary
- Source ID: `ticketmaster`
- Type: API (primary)
- Strategic role: mainstream concerts/sports/theater with high-fidelity metadata

## Access and Accounts
- Account type: API key
- Credential storage: secrets manager (`apikey`)
- Rate limits: 5 req/s, ~5000 req/day
- Account strategy:
  - `prod-main` key for scheduled ingestion
  - optional `backup` key for failover and key rotation drills

## Ingestion Strategy
- Endpoint: `GET /discovery/v2/events.json`
- Bay Area filtering: `dmaId=382`
- Sync modes:
  - bootstrap: `sort=date,asc`, max `size`
  - incremental: `modified_date.ge={last_sync}`
- Backoff: exponential retry on 429/5xx

## Field Mapping
- `name` -> `title`
- `dates.start.dateTime` -> `start_time`
- `_embedded.venues.*` -> `location.*`
- `priceRanges.min/max` -> `offers.price_min/max`
- `classifications.genre.name` -> `category_tags`
- `url` -> `source.source_url`

## Quality and Risk Controls
- Trust tier: highest for time/location precision
- Dedup preference: keep Ticketmaster title/time/location on merge conflicts
- Compliance: deep-link only; no ticket flow mirroring

## Operational Metrics
- Key metrics: rate-limit hit ratio, pages fetched, incremental delta volume
- Alert: abnormal drop in modified events or sustained 429s
