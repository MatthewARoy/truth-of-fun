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
- Respect `page * size < 1000`. A capped or failed search is incomplete and does not receive a completion timestamp. Date partitions now cover the configured 180-day horizon.
- The worker acknowledges completion only after the database transaction succeeds without rejected records.
- Backoff: exponential retry on 429/5xx

## Field Mapping
- `name` -> `title`
- `dates.start.dateTime` -> `start_time`
- `_embedded.venues.*` -> `location.*`
- `priceRanges.min/max` -> `offers.price_min/max`
- `classifications.genre.name` -> `category_tags`
- `url` -> `source.source_url`

## Coverage and completion
- Replay the next 180 days using date windows split below the 1,000-result deep-paging boundary. There is no modified-date incremental filter.
- Read undated TBA events separately, without date bounds, so postponements can update their original listings. Offsale means unavailable ticket sales, not a cancelled show.
- Limit each run to 80 page requests. Dense minimum windows, failed pages, and exhausted budgets remain visibly incomplete and cannot advance completion metadata.
- Acknowledge complete fetches only after ingestion commits. Completion describes this bounded horizon, not the whole provider catalog.

## Quality and Risk Controls
- Trust tier: highest for time/location precision
- Dedup preference: keep Ticketmaster title/time/location on merge conflicts
- Compliance: deep-link only; no ticket flow mirroring

## Operational Metrics
- Key metrics: rate-limit hit ratio, pages fetched, partial fetches, rejected records, changed canonical events
- Alert: incomplete pagination, abnormal result drops, or sustained 429s
- Provider contract: [Ticketmaster Discovery API v2](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/).
