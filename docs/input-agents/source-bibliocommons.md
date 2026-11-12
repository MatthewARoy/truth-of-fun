# Input Agent Spec: BiblioCommons Library Calendars (Oakland, San José)

## Source Summary
- Source IDs: `oakland_library` (Oakland Public Library), `san_jose_library` (San José Public Library)
- Type: API (public JSON gateway, no key)
- Code: `app/ingestion/sources/bibliocommons.py` — one `BiblioCommonsSource` class
  parameterised by a `BiblioCommonsLibrary` config; each library is its own registered source
- Strategic role: free East Bay / South Bay community programming — author talks, film
  screenings, craft and STEAM workshops, cultural celebrations, kids and family events
- Tier: 2
- Not available: San Francisco Public Library is not on this gateway (403)

## Access and Accounts
- Account type: none; public endpoint
  `GET https://gateway.bibliocommons.com/v2/libraries/<library>/events/search?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&limit=50&page=N`
- User-Agent: `truth-of-fun/0.1 (event discovery; +https://github.com/MatthewARoy/truth-of-fun)`
- Rate: 1 request/second

## Ingestion Strategy
- Use `/events/search`: the plain `/events` endpoint ignores the date parameters and is unsorted
- Response: `events.results` (ids, soonest first), `events.pagination {count, page, pages, limit}`,
  and `entities` (`events`, `locations`, `places`, `eventTypes`, `eventAudiences`, `images`)
- `limit` is capped at 50 by the server but echoed back as requested (`limit=100` returned
  50 rows and a `pages` computed for 100), so `page_size` stays at 50 and the crawl compares
  rows read against `count`
- Bounds: 30 pages and 200 events per library per run
  (2026-11-12, 14-day window: Oakland 257 rows / 6 pages, San José 961 rows / 20 pages)
- Filter, in order:
  1. not cancelled (`definition.isCancelled`)
  2. not recurring (`isRecurring`) — `include_recurring = False` by default; about 85% of
     rows are weekly storytimes and drop-in sessions
  3. not online (`definition.isVirtual`, or the `BC_VIRTUAL` pseudo-branch)
  4. starts inside the 14-day horizon
  5. not service-only: an event whose every type is a service or governance type
     (social/health/support services, library commission, volunteering, computer help,
     homework help) — `service_type_pattern`, set to `None` to disable

## Field Mapping
- `definition.title`, event `id` → `title`, `source.source_record_id`;
  `https://<library>.bibliocommons.com/v2/events/<id>` → `source.source_url`
- `definition.start/end` are Pacific wall-clock strings → UTC; a date-only value is an
  all-day event (local midnight–23:59, `start_time_is_estimated=true`)
- branch (`locations[branchLocationId]`) or off-site place (`places[nonBranchLocationId]`):
  name → `venue_name` (branches prefixed with the library name), `address` →
  postal-form address and `city`, `mapLocation.centrePoint` → `lat/lon` at confidence 0.9;
  no coordinates → city centroid at confidence 0.3
- `definition.description` (HTML) → plain text, ≤ 600 chars; featured image → `image_url`
- all events: `is_free=true`, price 0 USD; organizer = the library
- the staff `contact` block (name, email, phone) is never read
- categories from type names, by keyword, existing vocabulary only: Film, Music,
  Arts & Theatre, Fitness, Wellness, Outdoors, Food, Business, Miscellaneous (talks,
  author visits, STEAM/coding workshops); anything else → Social
- kids / family audiences (Kids, Toddlers, Babies, Families, Pre-Teens, … or a Storytime
  type) add the `familyfriendly` vibe tag (the product's "Family Friendly" filter) and the
  `Family` label, which the pipeline stores as a genre; no new top-level category

## Quality and Risk Controls
- Partial crawls (failed/garbled later page, page cap, event cap, fewer rows than `count`,
  missing pagination) keep what was read and set `last_fetch_error`; a failed first page raises
- `last_filter_counts` records how many rows each rule excluded
- Known limitation: cancelled events are skipped, so an event cancelled after it was
  ingested is not updated to `cancelled` by this source
- Adding a library: add a `BiblioCommonsLibrary` (gateway id = site subdomain), a
  subclass, the `SourceId` literal and a registry line

## Operational Metrics
- rows read vs events emitted, by exclusion rule (recurring share especially)
- pages per run against the 30-page cap
- share of events with `familyfriendly`
