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
- Fetch mode: replay `sort=date,asc`, max `size`, using persistent source IDs for idempotent updates.
- Discovery v2 does not document a modified-date filter. The local sync timestamp is completion metadata, not a delta cursor.
- Respect `page * size < 1000`. A capped or failed search is incomplete and does not receive a completion timestamp. Date-partitioned coverage beyond this cap remains follow-up work.
- The worker acknowledges completion only after the database transaction succeeds without rejected records.
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
- Key metrics: rate-limit hit ratio, pages fetched, partial fetches, rejected records, changed canonical events
- Alert: incomplete pagination, abnormal result drops, or sustained 429s
- Provider contract: [Ticketmaster Discovery API v2](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/).
