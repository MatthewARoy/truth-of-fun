# Platform review: Bay Area coverage and production readiness (2026-11-12)

A full review of the platform and its infrastructure, answering three
questions — is it comprehensive for the Bay Area, what would a user want that
is missing, and what does it take to run it in production — followed by the
work done in response and what is still open.

## Summary

**Before this review the platform was a well-tested San Francisco demo, not a
launchable Bay Area product.** The ingestion pipeline, dedupe, ranking and
sharing code were solid and covered by 838 passing tests. But:

- "Bay Area" was mostly San Francisco. Only Ticketmaster covered the whole
  region; Eventbrite crawled the SF listing alone; the hand-verified venue
  table was 97 San Francisco entries against 19 for the East Bay, 3 for the
  South Bay and 1 for the Peninsula; and the "Where" filter was a keyword
  match that offered three cities.
- There was no way to deploy the web app, no account recovery or deletion,
  rate limits that only worked for a single API process, an LLM call with a
  ten-minute default timeout on a public endpoint, and an ingestion worker
  that could hang forever without anyone being told.

**After the changes on this branch** the platform has a production stack that
was built and booted end to end, a real geography model with five regions and
79 cities, five additional sources outside San Francisco, a complete account
lifecycle, and a hardened API and worker. A live ingestion cycle in that stack
stored 1,878 events with no Ticketmaster key and no browser-driven sources.

**It is not finished.** The remaining blockers are mostly decisions and
accounts only the owner can provide (source terms, legal text, API keys, a
domain), plus the engineering items listed under [Still open](#still-open).
North Bay coverage in particular is still close to nil.

## How the review was done

- Three independent read-only audits (API and security; ingestion pipeline;
  web app and client packages), each reading the code in full, with findings
  cited to file and line. Claims were re-checked before being acted on.
- The existing suite was run against a local PostGIS and Redis to establish a
  baseline (838 passed), and re-run after every change (1,009 passed at the
  time of writing).
- Candidate sources were probed live with a small number of polite requests
  to confirm they exist and what they return.
- The production stack was built with Docker and started from an empty
  database; a full ingestion cycle ran against the live sources inside it.

## 1. Is it comprehensive for the Bay Area?

No — and it is measurably better than it was.

### What the sources covered (as found)

| Source | Geography actually requested | Notes |
| --- | --- | --- |
| Ticketmaster | DMA 382 (SF–Oakland–San Jose), 180 days | The only truly region-wide source. Needs an API key. |
| Eventbrite | `ca--san-francisco` listing only, 14 days | Tier 1, but one city. |
| 19hz | Bay Area listing | Region-wide; electronic music only. |
| DoTheBay, SF Station, FuncheapSF | Bay-wide calendars, 7–10 days | Region-wide in principle, but any venue missing from the static table was placed on the **San Francisco centroid** at low confidence, which hides it from radius search and files it under San Francisco. |
| Luma | `luma.com/sf`, first 50 | Tech/community; one city page. |
| Meetup | keyword `"bay area events"`, 20 results, no location | Needs a token; effectively unscoped. |
| Reddit | r/AskSF, r/bayarea, r/sanfrancisco | Needs credentials. |
| Minnesota Street, Stern Grove, Eddie's List | San Francisco | |

Static venue table: 97 San Francisco keys, 19 East Bay, 3 South Bay, 1
Peninsula, 4 North Bay. The geocoder that resolves everything else was off by
default.

The discovery side compounded this. `location_preset` offered `sf`, `oakland`
and `san_jose`, implemented as "the venue name, address or title contains that
word" — so a show at the Fox Theater, whose listing gives a street address,
was not in Oakland, and Berkeley, the Peninsula and Marin could not be asked
about at all.

### What changed

- **Geography model.** Every event now carries a `city` and a `region` (`sf`,
  `east_bay`, `peninsula`, `south_bay`, `north_bay`; `beyond` for Santa Cruz,
  Sacramento and the like), derived from its coordinates, or from the written
  address when the coordinates are only a centroid fallback. `GET /events`
  takes `region`, `city` and `is_free`; `GET /regions` lists what can be
  filtered with live counts; the concierge understands "in Oakland", "in the
  East Bay", "wine country". Existing rows are assigned by the worker with no
  separate backfill.
- **New sources**, each run live once:

  | Source | Result of one live run |
  | --- | --- |
  | Eventbrite, six more listings (Oakland, Berkeley, San Jose, Palo Alto, Walnut Creek, Santa Rosa) | 257 events from 18 requests: ~86 South Bay/Peninsula, 63 East Bay, 60 North Bay, 45 SF |
  | Stanford public events (Localist) | 259 rows before exhibitions were collapsed into ongoing rows |
  | San José State public events (Localist) | 67 |
  | Oakland Public Library (BiblioCommons) | 30 non-recurring, in-person events |
  | San José Public Library (BiblioCommons) | 93 (89 expected after excluding four online events found in that run) |

- **Venue table.** 47 venues outside San Francisco added — Oracle Park and
  the Cow Palace, Yoshi's, the Coliseum, Zellerbach, Berkeley Rep, Freight &
  Salvage, Concord Pavilion, Levi's Stadium, PayPal Park, the San Jose
  theatres, Mountain Winery, Bing Concert Hall, Stanford Stadium, the Fox in
  Redwood City, Mystic Theatre, Luther Burbank Center, Green Music Center and
  others — each checked against OpenStreetMap. The Fox Theater entries had
  been sitting on the Oakland city centroid, 350 m from the venue.
- **Venue matching.** Substring matching in both directions resolved
  "Oakland" to the Fox Theater, "San Jose" to the Civic and "Center" to Chase
  Center, all at full confidence. Matching is now on word boundaries.
- **Dates.** Listings without a year assumed the current year, so a January
  event seen in November was stored ten months in the past and immediately
  marked `past`. They now resolve to the next occurrence.
- **Production default.** The production stack enables geocoding, so venues
  outside the table are resolved over successive cycles instead of staying on
  a centroid.

### Measured after the change

One real ingestion cycle in the production stack, **without** a Ticketmaster
key, without the browser-driven sources (FuncheapSF, Luma), and with
Eventbrite blocked from that network path (see below):

| Region | Scheduled events stored |
| --- | --- |
| San Francisco | 1,191 |
| Peninsula | 255 (249 at Stanford, before exhibition collapsing) |
| South Bay | 188 (177 in San José) |
| East Bay | 123 (96 Oakland, 20 Berkeley) |
| North Bay | **2** |
| Outside the nine counties | 43 |

Two cautions when reading this. The San Francisco number is inflated: 429 of
SF Station's 596 events and 258 of DoTheBay's 394 had no resolvable venue and
sit on the San Francisco centroid until the geocoder (200 lookups per cycle)
works through them. And the non-SF totals would be higher with Eventbrite and
Ticketmaster contributing.

### Still thin or missing

Ordered by how much a resident would notice.

1. **North Bay** (Marin, Sonoma, Napa, Solano). Two events in the live run.
   The Santa Rosa Eventbrite listing helps; nothing else targets it. Needs
   its own sources — county and city calendars, the Marin and Sonoma arts
   centres, wine-country event listings.
2. **Ticketmaster is doing most of the regional work and needs a key.**
   Without `TICKETMASTER_API_KEY` there are no arena, stadium or major-theatre
   events at all, which includes essentially all professional sport.
3. **UC Berkeley public events.** The campus calendar exposes JSON
   (`events.berkeley.edu/live/json/events`, confirmed reachable); the
   connector was not built. This is the largest single East Bay gap.
4. **San Francisco Public Library** is not on the BiblioCommons gateway the
   Oakland and San José libraries use (it answers 403), so it needs its own
   connector. Library coverage also excludes recurring programmes by default
   (weekly storytimes would otherwise be ~80% of the rows); families may want
   those behind a filter.
5. **City, parks and civic calendars** — SF Rec & Park, Oakland, San José,
   East Bay Regional Parks, the peninsula cities. The earlier civic-coverage
   research (docs/research/2026-09-29-civic-coverage.md) recommends one
   configurable official-feed adapter; that is still the right design and is
   still unbuilt.
6. **Performing-arts organisations that sell their own tickets** (symphony,
   opera, ballet, the larger theatre companies, SFJAZZ, Cal Performances) and
   **independent venues' own calendars**. Not checked how many reach the
   catalog through Ticketmaster or the curator sites.
7. **Luma** reads one city page and the first 50 entries; **Meetup** sends no
   location and needs a paid API token; **Reddit** needs credentials. All
   three are the main sources for tech, community and hobby meetups.
8. **Recurring neighbourhood life** — farmers' markets, trivia nights, run
   clubs, open mics — arrives only incidentally through FuncheapSF.

Two known limits of the geography model: assignment is nearest-anchor, so a
venue near a city line can land in the neighbour (a Palo Alto community
centre resolved to Mountain View until an anchor was added); and several
Bay-wide scrapers still pass "San Francisco" as the city hint to the
geocoder, which can mis-resolve an out-of-city venue that shares a name with
a San Francisco one.

## 2. What would a user want that is missing?

| Capability | Before | Now |
| --- | --- | --- |
| Browse by region or city across the Bay | 3 cities, keyword match | Regions and cities, by location (API + Explore) |
| Free-only filter | — | `is_free` (API + Explore) |
| Date / date-range picker | API only | Explore |
| "Near me" with distance sort | API only | Explore |
| A page and link for one event | — | `/events/{id}`, shareable, with preview metadata |
| Add to calendar | — | `.ics` download per event |
| Forgot password | — | Emailed reset link |
| Change password, sign out everywhere | — | Account page |
| Download my data, delete my account | — | Account page |
| Shareable search URLs | — | Explore state in the query string |
| Saved-events list, un-save | Save signal only | **Missing** |
| Email digest or alerts for a saved search / venue / artist | — | **Missing** |
| Transit-aware planning (BART/Muni/Caltrain times) | Travel-mode links only | **Missing** — legs are straight-line estimates |
| Price range filter, sold-out state | — | **Missing** (prices are sparse outside Ticketmaster) |
| Family / kids filter in the UI | Vibe tag only | **Missing** as a first-class filter |
| Accessibility information | — | **Missing** — no source publishes it consistently |
| Sign in with Google / Apple | — | **Missing** |
| Email verification | — | **Missing** — an address can be registered by someone who does not own it |
| Submit an event, report a wrong listing | — | **Missing** |
| Follow a venue or performer | — | **Missing** |
| Languages other than English, light theme, installable app | — | **Missing** |

See [the web section](#web-application) for the state of each web item.

## 3. What does it take to productionize?

### Findings and what was done

Severity is for a public launch. "Fixed" means implemented on this branch
with tests; "Open" items are collected below.

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | No production deployment for the web app; API URL fell back to `127.0.0.1` in the browser bundle | Blocker | **Fixed** — `deploy/` stack, web image, same-origin `/api` |
| 2 | No password reset, account deletion or data export | Blocker | **Fixed** — API and pages |
| 3 | Rate limits per process and reset on restart; nothing on search, detail or folders | Blocker | **Fixed** — Redis-backed windows, a general per-client ceiling on every route, IPv6 keyed by /64 |
| 4 | Concierge LLM client had the SDK's 10-minute timeout and 2 retries on a public endpoint | Blocker | **Fixed** — 8 s, no retries, keyword fallback |
| 5 | Ingestion worker had no timeout around a source: one silent host stalled every later cycle | High | **Fixed** — per-source budget, heartbeat, watchdog exit, `--healthcheck` |
| 6 | No single-instance guard: two workers double-crawl and duplicate events | High | **Fixed** — Postgres advisory lock per cycle |
| 7 | Migrations ran in the API container's start command (unsafe with replicas); worker ran `create_all` | High | **Fixed** in the production stack (one-shot `migrate` job); worker now refuses an unmigrated database |
| 8 | DB pool at defaults (5+10) against 40 request threads; no statement timeout; bound parameters (emails, hashes, tokens) in error text | High | **Fixed** — sized pool, `statement_timeout` for the API, `hide_parameters` |
| 9 | Default feed walked the start-time index from the oldest row; radius search could not use the spatial index | High | **Fixed** — partial index on scheduled rows, geography GiST index (verified with `EXPLAIN` on 100k rows: 0.04 ms and 6.6 ms) |
| 10 | Share, invite and folder tokens written to access logs via the URL path; no client address in logs | Medium | **Fixed** — route template and client IP logged |
| 11 | Bad input returned 500 (NUL bytes, huge offsets) and write races surfaced as 500 | Medium | **Fixed** — 400 / 409, bounded offset |
| 12 | No error reporting | Medium | **Fixed** — optional Sentry for API and worker, URLs scrubbed |
| 13 | JWTs could not be revoked for 7 days | Medium | **Fixed** — version claim; password change, reset and "sign out everywhere" revoke |
| 14 | `Bob@x` and `bob@x` were separate accounts | Low | **Fixed** — case-insensitive lookup |
| 15 | Canary baseline and health history lost on every restart; identical alerts every cycle | Medium | **Fixed** — state restored from the database, 24 h alert cooldown |
| 16 | Health page permanently red: unconfigured optional sources and budget-capped crawls reported as failing | Medium | **Fixed** — `disabled` status; capped crawls are `degraded` |
| 17 | `preferred_vibes` could grow without bound through "like", each entry a subquery in ranking | High | **Fixed** — capped at 50 |
| 18 | No backups | Blocker for real data | **Fixed** — nightly `pg_dump` with retention; restore documented. Off-host copy is the operator's to schedule |
| 19 | CI did not build the production images | Medium | **Fixed** — `deploy-ci` builds, boots and smoke-tests the stack; Dependabot added |
| 20 | CI red on new advisories in already-locked dependencies | — | **Fixed** — certifi and dnspython (Python); `npm audit fix` cleared the high and critical JavaScript advisories |
| 21 | Web Dockerfile and compose were never built anywhere | — | **Fixed** — both images were built and the stack run; one install-order bug in the new web Dockerfile was found and fixed that way |

### Web application

The web audit found no deploy path, no route-level error handling, nothing
for crawlers or link previews to read, no handling of an expired session, and
an Explore page that surfaced a fraction of what the API could already do.

Done on this branch:

- **Resilience.** `error.tsx`, `global-error.tsx` and `not-found.tsx`; an
  expired or revoked session now clears itself and returns the user to sign
  in (previously the app kept showing them as signed in over raw API errors);
  validation errors read as sentences instead of "Request failed: 422"; GET
  requests no longer trigger a CORS preflight; every path token is encoded.
- **Shareability.** A server-rendered page per event (`/events/{id}`) with
  title, description, canonical URL, Open Graph and Twitter tags and
  schema.org `Event` JSON-LD, returning a real 404 for unknown ids; preview
  metadata on shared itineraries and folders; `robots.txt`, a sitemap of
  static routes plus upcoming events, and `noindex` on token, account and
  admin pages; one `<h1>` per page with the header outside `<main>`.
- **Security headers.** A Content-Security-Policy (verified with no
  violations on every page including the map), HSTS, `X-Powered-By` removed.
- **Explore.** Region chips and a city selector with live counts, a Free
  toggle, date and date-range picking in Pacific time, "Near me" with a
  radius and distance sort, all state in the URL; cards show price or "Free"
  and the city, link to the event page, and only render `https` images and
  `http(s)` links; the map no longer plots low-confidence centroid guesses as
  venue pins.
- **Account.** Forgot / reset password pages and an account page: interests,
  change password, sign out everywhere, download my data, delete account.
- **Copy and legal.** The home page is written for residents rather than
  engineers. `/privacy` and `/terms` exist as factual drafts, each marked at
  the top as pending legal review, with placeholders for the company name,
  contact, retention periods and service providers.

Verified: lint, typecheck and production build pass; 94 browser tests pass
against a mocked API (41 before); the two real-API browser tests pass
(signup → plan → publish → public read → revoke, and the MCP token
lifecycle); and a browser walkthrough of the production stack through the
Caddy edge — region filter, event page, calendar download, signup, account
page, data export, password-reset request — produced no console errors and no
5xx responses.

Known limits: the CSP allows inline scripts and styles (the pages are
statically rendered, so there are no nonces); event images are still loaded
directly from their source sites; "Near me" replaces the region filter rather
than combining with it and is not kept in the URL; there is no default
preview image for pages without an event image; `global-error.tsx` builds
but was not exercised in a browser; the navigation wraps to two rows on a
phone-width screen.

### What was verified, and how

- Backend: 1,009 tests pass against PostGIS 16 and Redis 7 (838 before).
- Web: lint, typecheck, production build, 26 API-client tests, 11 MCP-server
  tests, 94 browser tests and 2 real-API browser tests pass.
- The production stack was built and started from an empty database:
  `migrate` exited 0, and `caddy`, `web`, `api`, `worker`, `db`, `redis` and
  `backup` came up healthy. Through the edge: HTTP redirects to HTTPS, the
  web app and `/api` share one origin, the operator endpoints answer 403
  without the token, and `/api/internal/*` is not routed.
- In that stack: after one registration, 25 bad logins spread across two
  uvicorn workers produced 19 `401`s and then 6 `429`s — exactly the
  20-per-window limit, shared through Redis; a second
  `worker --once` was refused while the first held the lock; the API
  connection reported `statement_timeout = 15s`; the first backup file was
  written.
- A full ingestion cycle ran in the stack against live sources (numbers
  above).

Not verified here: TLS issuance against a real domain, SMTP delivery to a real
mailbox, Sentry delivery, the worker image's Chromium (the validation run used
the API image, so FuncheapSF and Luma failed there by construction), and
behaviour under load.

## Still open

### Decisions and inputs only the owner can provide

1. **Scraping posture.** FuncheapSF and Luma are fetched with a headless
   browser using stealth settings and optional proxy rotation; DoTheBay with a
   browser User-Agent; none of the scrapers checks `robots.txt`. Eventbrite's
   connector is labelled `metadata_only` / `tos_risk=medium` yet stores full
   descriptions. This is the largest non-technical launch risk and needs a
   per-source decision: license or use an official feed, keep as is, or switch
   off. Nothing was changed here because it is a policy call, not a bug.
2. **The scraped sources may simply not work from a server.** In the live
   run Eventbrite answered the container's requests with an AWS WAF CAPTCHA
   (HTTP 405, `x-amzn-waf-action: captcha`) while the same URL returned 200
   from another egress path a minute later; DoTheBay returned 403 to the
   project's honest User-Agent and 200 to the HTTP library's default one.
   Expect datacenter addresses to be challenged. Source health reports it
   when it happens, but the fix is a licensed feed or a proxy, which is a cost
   decision.
3. **Credentials**: Ticketmaster (most important), Anthropic (vibe tags and
   intent parsing), Meetup, Reddit, an SMTP provider, a Sentry project, an
   alert webhook.
4. **Legal**: privacy policy and terms reviewed by counsel; a decision on
   hot-linking third-party images versus proxying them; map-tile terms.
5. **A domain and a host**, then the checklist at the end of
   [deployment.md](./deployment.md).

### Engineering, in suggested order

1. **Dedupe can merge different events.** Same title at the same venue two
   hours apart (early and late shows, "Game 1"/"Game 2") fuzzy-match and the
   later one never appears; conversely "The Fillmore" and "Fillmore" stay
   separate rows. Needs: never fuzzy-merge two different ids from one source,
   and require venue or URL corroboration. Left alone here because it changes
   which events exist and deserves its own review against real data.
2. **Listings that disappear stay `scheduled`** until their date passes; there
   is no per-source last-seen. A cancelled show pulled from a curator site
   keeps being served.
3. **Recommendations ranking** builds one correlated subquery per weighted
   tag; now bounded at 50 tags, but it should move to an indexed `jsonb` tag
   column before the catalog or user base grows.
4. **`user_signals` grows without bound** (every click is a row, all of a
   user's rows are re-read per request), and `saved_event_ids` is a JSON list
   on the user row with lost-update races and no un-save. Needs a
   `saved_events` table and signal dedupe.
5. **The concierge endpoint is `async` but runs synchronous SQL and scoring
   on the event loop**, with deliberately unbounded candidate queries. The
   LLM timeout removes the worst failure; the query shape is still the first
   thing that will slow down as the catalog grows.
6. **Default clock times are not flagged as estimated** in several connectors
   (DoTheBay, SF Station, 19hz, Stern Grove, Minnesota Street), so a guessed
   19:00 is shown as a published start.
7. **One rejected row marks every source's cycle incomplete** because the
   pipeline does not attribute rejections to sources.
8. **Geocoding and tagging await inside an open transaction** (seen as
   `idle in transaction` during the live run).
9. **Email verification, a web-side error reporter, and metrics** (request
   rate, latency, LLM spend) do not exist.
10. **JWT in `localStorage`.** Mitigated by the new CSP and revocation, but an
    httpOnly cookie through the same-origin edge is the proper fix now that
    web and API share an origin.
11. **Folder share links never expire** and folders, items and members cannot
    be deleted individually.
12. **Onboarding's tag extractor is a heuristic** that stores words from the
    sentence as tags ("#perfect", "#saturday") and spends the LLM rate budget
    without calling an LLM.
13. **No pruning** of past events or of the geocode and vibe-tag caches.
14. **Eight moderate `npm audit` advisories remain** in lint tooling
    (the typescript-eslint chain); fixing them needs a major-version bump.
    The high and critical ones were resolved on this branch.
