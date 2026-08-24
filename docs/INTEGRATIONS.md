# Integration Testability Matrix

Playwright-based scrapers (FuncheapSF, Luma) need browser binaries: `make install` runs `.venv/bin/playwright install chromium` for you (best-effort), or run it manually.

| Source | Testable | Notes |
|--------|----------|-------|
| **Ticketmaster** | No | Requires `TICKETMASTER_API_KEY` or AAIM secrets |
| **Eventbrite** | Yes | Public scraper, no API key |
| **Meetup** | No | Requires `MEETUP_API_TOKEN` |
| **FuncheapSF** | Yes | Playwright scraper, no API key |
| **19hz** | Yes | Public httpx scraper |
| **Luma** | Yes | Playwright scraper; Cloudflare may block without proxy |
| **DoTheBay** | Yes | Public httpx scraper |
| **SF Station** | Yes | Public httpx scraper |
| **Minnesota Street Project** | Yes | Public httpx scraper |
| **Reddit** | No | Requires `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (script app); anonymous search.json is 403-blocked |
| **Eddie's List** | No | Requires IMAP credentials (mailbox integration) |

## NOT_TESTABLE Sources

These require credentials or external setup to run:

- **Ticketmaster**: `TICKETMASTER_API_KEY` env or the AAIM secrets store (see [architecture.md → Enabling AAIM key rotation](./architecture.md#enabling-aaim-key-rotation))
- **Meetup**: `MEETUP_API_TOKEN` env
- **Reddit**: `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` env (Reddit script app; anonymous search.json returns 403)
- **Eddie's List**: IMAP mailbox credentials (`IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`)

## Reusable Code

- `app/ingestion/scraper_utils.py`: Shared parsing (dates, prices, HTML strip)
- `app/ingestion/input_agent.py`: `InputAgentSource` base for discover → extract → normalize pipeline
