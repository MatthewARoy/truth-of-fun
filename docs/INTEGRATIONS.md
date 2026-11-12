# Integration Testability Matrix

Playwright-based scrapers (FuncheapSF, Luma) need browser binaries: `make install` runs `.venv/bin/playwright install chromium` for you (best-effort), or run it manually.

| Source | Testable | Notes |
|--------|----------|-------|
| **Ticketmaster** | No | Requires `TICKETMASTER_API_KEY` or AAIM secrets |
| **Eventbrite** | Yes | Public scraper, no API key; crawls SF, Oakland, Berkeley, San Jose, Palo Alto, Walnut Creek and Santa Rosa listings (≤ 43 requests/run) |
| **Meetup** | No | Requires `MEETUP_API_TOKEN` |
| **FuncheapSF** | Yes | Playwright scraper, no API key |
| **19hz** | Yes | Public httpx scraper |
| **Luma** | Yes | Playwright scraper; Cloudflare may block without proxy |
| **DoTheBay** | Yes | Public httpx scraper |
| **SF Station** | Yes | Public httpx scraper |
| **Minnesota Street Project** | Yes | Public httpx scraper |
| **Reddit** | No | Requires `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (script app); anonymous search.json is 403-blocked |
| **Eddie's List** | No | Requires IMAP credentials (mailbox integration) |
| **Stanford Events** (`stanford_events`) | Yes | Localist public JSON API (`events.stanford.edu/api/2/events`), no key; public in-person events only |
| **SJSU Events** (`sjsu_events`) | Yes | Localist public JSON API (`events.sjsu.edu/api/2/events`), no key; public in-person events only |
| **Oakland Public Library** (`oakland_library`) | Yes | BiblioCommons public JSON gateway, no key; one-off events only |
| **San José Public Library** (`san_jose_library`) | Yes | BiblioCommons public JSON gateway, no key; one-off events only |

## Non-source integrations

| Service | Key needed | Notes |
|---------|-----------|-------|
| **Nominatim (OpenStreetMap)** | No | Geocodes venues missing from the static coordinate table. Off unless `GEOCODING_PROVIDER=nominatim`. Capped at 1 request/second by [their usage policy](https://operations.osmfoundation.org/policies/nominatim/), which also requires the descriptive `GEOCODING_USER_AGENT`. Unreachable or unconfigured degrades to the city-centroid fallback. Google and Mapbox would need billing accounts and are not implemented. |

## NOT_TESTABLE Sources

These require credentials or external setup to run:

- **Ticketmaster**: `TICKETMASTER_API_KEY` env or the AAIM secrets store (see [architecture.md → Enabling AAIM key rotation](./architecture.md#enabling-aaim-key-rotation))
- **Meetup**: `MEETUP_API_TOKEN` env
- **Reddit**: `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` env (Reddit script app; anonymous search.json returns 403)
- **Eddie's List**: IMAP mailbox credentials (`IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`)

## Reusable Code

- `app/ingestion/scraper_utils.py`: Shared parsing (dates, prices, HTML strip)
- `app/ingestion/input_agent.py`: `InputAgentSource` base for discover → extract → normalize pipeline
