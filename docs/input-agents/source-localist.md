# Input Agent Spec: Localist University Calendars (Stanford, SJSU)

## Source Summary
- Source IDs: `stanford_events` (events.stanford.edu), `sjsu_events` (events.sjsu.edu)
- Type: API (public JSON, no key)
- Code: `app/ingestion/sources/localist.py` — one `LocalistSource` class parameterised by a
  `LocalistCampus` config; each campus is registered as its own source so health,
  canary history and partial-crawl errors are tracked per calendar
- Strategic role: Peninsula / South Bay coverage from official calendars — exhibitions,
  recitals, theatre, public lectures, tours, home athletics
- Tier: 2

## Access and Accounts
- Account type: none; public endpoint `GET <base>/api/2/events?days=14&pp=100&page=N`
- User-Agent: `truth-of-fun/0.1 (event discovery; +https://github.com/MatthewARoy/truth-of-fun)`
- Rate: 1 request/second

## Ingestion Strategy
- The API returns one row per *occurrence* in the window:
  `{"events":[{"event":{…,"event_instances":[{"event_instance":{id,start,end,all_day}}]}}],
  "page":{"current","size","total"}}`
- Follow `page.total`; bounds: 8 pages and 500 events per run
  (2026-11-12: Stanford 474 rows / 5 pages, SJSU 241 rows / 3 pages)
- One canonical event per occurrence inside the 14-day horizon;
  `source_record_id` is the occurrence (`event_instance`) id
- Public-interest filter (`LocalistSource.exclusion_reason`), in order:
  1. `status == "live"`, not `private`
  2. `experience` is `inperson` or `hybrid` (virtual-only is dropped)
  3. no blocked event type, and at least one allowlisted type (per campus, below)
  4. where the row has an audience filter, it includes `General Public` or `Everyone`
     (no audience filter at all is allowed)
  5. title is not study recruitment ("clinical research study", "participants needed")
  6. the place can be located (not "TBA", not an out-of-state away game)

| Campus | Allowlisted types → category | Blocked / not allowlisted |
|--------|------------------------------|---------------------------|
| Stanford (`filters.event_types`, audience in `filters.event_audience`) | Exhibition → Arts & Theatre; Performance → Arts & Theatre; Film/Screening → Film; Lecture/Presentation/Talk, Tour, Workshop → Miscellaneous; Social Event/Reception → Social; Fitness/Recreational Sport → Fitness | Blocked: Academic Dates, PhD Defense, Meeting, Support Space. Not allowlisted: Class/Seminar, Conference/Symposium, Religious/Spiritual, Other, untyped |
| SJSU (audience in `filters.event_target_audience`) | Exhibitions, Performances, Installations → Arts & Theatre; Athletics Events → Sports; Social Events and Gatherings → Social; Visitors and Tourism, Conferences, Training, Workshops → Miscellaneous | Not allowlisted: Info Sessions, Fairs and Events; untyped rows (about half the feed: student-org events with the location behind a sign-in) |

## Field Mapping
- `title`, `localist_url` → `title`, `source.source_url`
- `event_instance.start/end` (ISO with offset) → `start_time`/`end_time` in UTC
- `all_day` → local midnight to 23:59 (or the published end), `all_day=true`,
  `start_time_is_estimated=true` — no clock time is invented
- `geo.latitude/longitude` → `location.lat/lon` at confidence 0.9; `geo.city` → `location.city`;
  address emitted in postal form (`"541 Lasuen Mall, Stanford, CA 94305"`)
- no `geo`: a known venue within 15 km of campus (venue cache), else the campus centroid at
  confidence 0.3 with `"<City>, CA"` as the address; a `"City, Calif."` venue (athletics)
  uses that city's centroid; out-of-state or unknown cities are dropped
- `free: true` or a "Free…" `ticket_cost` → `is_free`, price 0; `$` amounts → `price_min/max`;
  `free: false` with no cost text means *not stated* (price left empty)
- `description_text` → `description` (plain text, ≤ 600 chars); `photo_url` → `image_url`
- first department/group name → `organizer.name`, else the university
- event types also set vibe tags from the existing vocabulary (`art`, `film`,
  `intellectual`, `workshop`, `social`, `sports`)

## Quality and Risk Controls
- A venue-cache hit far from campus is treated as a name collision ("Mezzanine")
- Partial crawls (failed/garbled later page, page cap, event cap, missing pagination)
  keep what was read and set `last_fetch_error`; a failed first page raises
- `last_filter_counts` records how many rows each rule excluded; an all-excluded run
  explains itself in `last_empty_reason`
- Known limitation: a long-running exhibition is one row per open day (on 2026-11-12,
  149 of Stanford's 259 emitted rows were 17 exhibitions)
- Adding a campus: add a `LocalistCampus` (types differ per campus), a subclass, the
  `SourceId` literal and a registry line

## Operational Metrics
- rows read vs events emitted, by exclusion rule
- share of events on feed coordinates (0.9) vs campus centroid (0.3)
- new event types appearing in the feed that are neither allowlisted nor blocked
