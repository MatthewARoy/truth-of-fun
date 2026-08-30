# Truth of Fun — user-lens review

**Date:** 2026-08-13 · **Reviewed against:** the running app (Docker: API :8000, web :3002) with the live
ingested database of **1,578 events** from 9 active sources — not the 20-row demo seed.

Every claim below carries evidence: a `file:line`, a SQL result, or an HTTP response I ran against the
running stack. Where I'm assuming, it says `[ASSUMED]`.

---

## The one-sentence finding

**Truth of Fun answers "what should I do Friday night?" It has no way to answer "what could I become
part of?"** — because the object a growth-community *is* (a group that meets repeatedly, run by
somebody, that you join and come back to) does not exist anywhere in the system.

That single absence causes two failures at once, at opposite ends of the product:

- **You can't find communities.** Searching the live catalogue: `bouldering` → 0 results,
  `makerspace` → 0, `beginner` → 0, `pottery` → 0, `climbing` → 1, `run club` → 1, `chess` → 1,
  `soccer` → 1. Out of 1,578 events.
- **The feed is spammed by the very thing that should be a community.** 35.7% of upcoming rows
  (525 of 1,471) are repeat listings of just 157 titles. "Alex Ramon Magic" is 32 separate cards.
  "Laugh Factory" is 22. Nothing collapses them, because there is no series to collapse them into.

Fix the missing object and you fix both ends. That's the spine of this review.

---

## Part 0 — Ground truth

### What's actually in the database

| Source | Events | with categories | with organizer | with tags |
|---|---:|---:|---:|---:|
| ticketmaster | 969 | 969 | 0 | 965 |
| 19hz | 307 | 0 | 0 | 307 |
| funcheap_sf | 183 | 0 | 0 | 0 |
| eventbrite | 30 | 0 | 0 | 30 |
| sfstation | 27 | 0 | 0 | 0 |
| luma | 20 | 20 | 0 | 0 |
| dothebay | 16 | 0 | 0 | 0 |
| minnesotastreet | 15 | 15 | 15 | 0 |
| sterngrove | 11 | 11 | 11 | 11 |
| **meetup** | **0** | — | — | — |
| **reddit** | **0** | — | — | — |
| **eddies_list** | **0** | — | — | — |

`[VERIFIED: psql group-by over the live events table]`

**The three most community-shaped sources produce nothing.** Meetup is the only connector in the
entire system that natively models "a group that meets repeatedly" — and it has contributed zero
rows. The README advertises 11 sources; 9 have data.

### Field completeness across all 1,578 events

| Missing | Count | % |
|---|---:|---:|
| organizer_name | 1,552 | 98.4% |
| description | 958 | 60.7% |
| categories | 563 | 35.7% |
| price | 1,123 | 71.2% |
| image | 609 | 38.6% |
| tags | 265 | 16.8% |
| location_confidence < 0.5 | 426 | 27.0% |

`[VERIFIED: single aggregate query over events]`

---

## Part 1 — Broken right now

These four are not design opinions. I reproduced each against the running app.

### 1.1 The category filter returns zero results on a fresh Explore page

Load `/explore`, click **Music** → **"0 events — No events found. Try adjusting your filters."**
The database holds **447** events categorised Music.

Three compounding causes:

- The chips filter **client-side over the 20 already-loaded rows**
  ([explore/page.tsx:94-96](apps/web/app/explore/page.tsx:94)) — there is no server-side category
  parameter on `GET /events` at all.
- **"Load more" is hidden whenever a chip is active** ([explore/page.tsx:245](apps/web/app/explore/page.tsx:245)),
  so the user cannot escape the 20-row window.
- The 6 chips are hardcoded Ticketmaster segment names
  ([explore/page.tsx:34-36](apps/web/app/explore/page.tsx:34)). The first 20 rows by date are
  funcheap / luma / sfstation events — **0 of which carry any tag, and 15 of which carry no category
  at all.**

The user's reasonable conclusion is "this app has no music events." Worse for this review's purpose:
the real category vocabulary in the database includes `community` (20), `social`, `tech`, `startup`,
`gallery`, `arts`, `festival` — **none of which has a chip.** The categories where communities live
are unreachable by design.

**Fix:** make category a real server-side filter; build the chip list from the data (there is no
endpoint that returns which tags/categories exist — add one); never suppress pagination on a filter.

### 1.2 `?vibe_tag=` returns HTTP 500

```
GET /events?vibe_tag=%23LiveMusic  →  HTTP 500 Internal Server Error
```

`Event.tags` is a `sqlalchemy.JSON` column, whose comparator has no `contains`, so
`Event.tags.contains([vibe_tag])` ([discovery.py:441](app/api/discovery.py:441)) falls back to
string-LIKE and emits SQL Postgres rejects (`operator does not exist: json ~~ text`). Nothing catches
it. `[VERIFIED: live request against the running API]`

This is the **only** tag filter the API has, it has zero test coverage, and the one UI that calls it
(the folder page's free-text vibe box) hands the user a 500.

**Fix:** `jsonb` column + a GIN index + `@>` containment. That also makes tag filtering fast enough
to be a primary navigation surface, which the community work below needs.

### 1.3 Onboarding discards most of what the user told you

The signup vibe picker has 16 well-chosen structured tags. It **throws the structure away**: it maps
chips to their human labels, joins them into the sentence `"I enjoy <labels>"`, and posts that free
text ([login/page.tsx](apps/web/app/login/page.tsx)) to an endpoint that re-tokenises it with a
regex word/bigram heuristic — not an LLM.

Selecting **Comedy, Art & Museums, Outdoors & Nature, Free Events** yields:

```
['#Enjoy', '#EnjoyComedy', '#Comedy', '#ComedyArt', '#Museums']
```

`[VERIFIED: ran HeuristicOnboardingTagExtractor on the real input inside the API container]`

Three of five stored tags are nonsense, the extractor hard-stops at 5 candidates, and **"Outdoors &
Nature" and "Free Events" are dropped entirely.** These junk tags are then displayed back to the user
under *"We tuned recommendations for:"*.

The downstream effect, end to end on a real account:

```
register → pick those 4 vibes → GET /recommendations
  75%  Sister Act                          matched=['#comedy']
  75%  Danny Jolles                        matched=['#comedy']
  75%  Stand-Up Comedy at Mr. Bing's       matched=['#comedy']
  75%  Danny Jolles                        matched=['#comedy']
  ... 10 of 10 comedy, "Danny Jolles" three times
```

`[VERIFIED: live register + onboarding + recommendations against the running API]`

**Fix:** send the structured tags. The picker already has them. This is a client-side change of a few
lines that repairs the entire cold-start path.

### 1.4 The planner turns a community request into a night out — in the wrong city

**388 events (25% of the catalogue) sit on the exact SF centroid `37.7749, -122.4194`, covering 181
distinct real venues.** `[VERIFIED: coordinate group-by]`

I asked the planner: *"I just moved here and want to find a bouldering club or makerspace I could join
every week as a beginner."* It returned a **49ers game at Levi's Stadium** — *"4900 Marie P. DeBartolo
Way, Santa Clara"*, `location_confidence 0.4` — with **driving directions, parking, and "food nearby"
links all pointing at downtown San Francisco, ~40 miles away.**

Two separate failures in one response, and both matter:

**It didn't fail loudly — it silently became a night out.** The concierge classified that query as
`general_night_out`, because that is the fallback of a **four-value intent vocabulary**:
`date_night`, `out_of_town_guests`, `bar_crawl`, `general_night_out`
([concierge.py:61-67](app/services/concierge.py:61)). The LLM prompt constrains the model to the same
four ([concierge.py:232](app/services/concierge.py:232)). **There is no intent for joining, learning,
or belonging** — so a community-seeking request can't be recognised as one, and the user gets a
confident wrong answer instead of "I can't help with that yet."

**And the coordinates were fabricated.**

The backend does know: radius search excludes `location_confidence < 0.5` by default. But that guard
only fires when `lat/lng/radius_miles` are supplied, and **no UI surface ever sends them**
([explore/page.tsx:55-58](apps/web/app/explore/page.tsx:55)). The itinerary builder applies no guard
at all, and the coordinates get **frozen into the public shared-itinerary link**.

`location_confidence` is also stripped out of the shared TypeScript type
([types.ts:1-19](packages/api-client/src/types.ts:1)), so the frontend *cannot* warn the user even if
it wanted to.

**Fix:** never emit directions from a low-confidence point; show "approximate location" on the card
and map; add `location_confidence` back to the client type. This one is a trust bug — it contradicts
the project's own stated data-integrity principle about not fabricating coordinates. Separately, add a
`find_a_community` intent and let the planner say "I don't have that yet" rather than substituting a
night out.

---

## Part 2 — The community spine

### 2.1 Make the group a first-class object

There is **no entity, table, column, index, endpoint, or UI element representing "a group that meets
repeatedly."** `[VERIFIED: all 11 ORM models, all 10 migrations, whole-tree grep for
recurring/rrule/series/cadence/troupe/league/roster/cohort]` The only trace of group identity is
`events.organizer_name`, an unindexed nullable `VARCHAR(255)`.

Introduce a `Series` (or `Group`) with an organizer, a cadence, and a home venue; give `Event` a
nullable `series_id`. That one object pays for itself immediately in three places:

- **Explore stops repeating itself.** Collapse the 157 repeating titles into one card each —
  "Laugh Factory · 22 upcoming dates" — recovering 35.7% of the feed for actual variety.
- **"For You" stops being monotonous.** The diversity penalty currently keys on `categories[0]`
  ([recommender.py:168-177](app/services/recommender.py:168)), which 36% of events don't have, is
  worth exactly −10 (cancelling only the flat +10 diversity term), and is applied once against the
  pre-penalty order and then re-sorted. Series is the right key, and it's the reason "Danny Jolles"
  appeared 3× in a 10-item feed.
- **Communities become findable at all** — everything below depends on it.

### 2.2 Fix the organizer pipeline end to end

98.4% of events have no organizer. Every link in the chain leaks:

- **Meetup's GraphQL query asks for only `group { name url }`**
  ([meetup.py:115-118](app/ingestion/sources/meetup.py:115)) — no group id, urlname, topics, or
  membership count. It reads `raw_item['topics']` for categories but **never selects `topics`**, so
  that is always empty.
- **`organizer_url` is dropped entirely** — declared at
  [contracts.py:64](app/ingestion/contracts.py:64), assigned once in meetup.py, never persisted,
  typed, or rendered. And because it's typed `HttpUrl` inside a `try` that swallows
  `ValidationError`, a malformed group URL **silently discards the whole event**.
- **Ticketmaster's `_embedded.attractions[].name`** — the closest thing to a recurring performer
  identity in any source — is flattened into the free-text `tags` list
  ([ticketmaster.py:286-295](app/ingestion/ticketmaster.py:286)).
- **DoTheBay's weekly listings are deliberately flattened** into one-off dated rows; the weekly-ness
  is discarded (`tests/test_ingestion_dothebay.py:65-69`).
- **`organizer_name` is stripped at the typed-client boundary** — the shared `EventResponse` omits it
  along with `is_free`, `attendee_count`, and `location_confidence`
  ([types.ts:1-19](packages/api-client/src/types.ts:1)) — so the API sends it and the frontend
  literally cannot compile against it. The string "organizer" appears **nowhere** in the web app.
- **`organizer_name` isn't even searchable** — `search_vector` is built from title + description only
  ([202603300002_add_fulltext_search.py:16-18](alembic/versions/202603300002_add_fulltext_search.py:16)).

Note the spec already calls for this: `docs/input-agents/source-meetup.md` says *"recurring community
events and group-driven social signal"* and maps group name/url → `organizer.*`. The design exists;
the implementation doesn't.

### 2.3 Add the verb that's missing: **Follow**

Every verb in the product is one-off — *Save*, *Viewed*, *Tickets*, *Add to folder*. There is no way
to express "I want to keep showing up to this."

Follow a group → its next meeting appears in For You without competing on vibe-tag arithmetic; you
get a "your groups" surface; the recommender gets the strongest possible signal. This is also the
only signal that survives the current recommender's structural filter (see 3.2).

### 2.4 Ingest where communities actually live

No amount of re-ranking will surface a makerspace that isn't in the database. The current mix is
tickets (969), club nights (307), and free one-offs (183). Missing entirely: rec leagues, climbing
gyms, makerspaces, run clubs, community colleges, libraries, tool libraries, hackerspaces, dojos,
choirs, community gardens.

Concretely for the Bay Area: **get Meetup working** (it's built and returning nothing), and add
Noisebridge / The Crucible / SF Rec & Park classes / library event calendars / Strava-style club
listings.

### 2.5 Give growth its own facets

"Beginner-friendly", "drop-in vs. commitment", "free", "meets weekly", "gear provided" are the
questions someone joining a community actually asks, and none is expressible today. The API has **no
price filter, no free-only filter, no day-of-week filter, and no time-of-day filter** — and `is_free`
is computed, stored, and serialised, then dropped by the frontend type, so a free event and an
unpriced event render identically: as nothing.

The LLM vibe-tagger is the natural place to extract these — but note it can only see a description,
and **60.7% of events don't have one.**

---

## Part 3 — Discovery fundamentals

### 3.1 Search can't find things that are in the database

`search_vector` covers title + description only — **not venue, not organizer, not tags, not
categories**. Since 60.7% of events have no description, search is effectively **title-only** for most
of the catalogue. And `plainto_tsquery` ANDs the terms, so every extra word narrows: `comedy` → 175
results, `comedy show` → 134; `jazz` → 4, `live jazz` → 1. A natural query like "beginner pottery
class" returns nothing.

**Fix:** add venue_name, organizer, tags, and categories to the tsvector (weighted); fall back to OR
/ trigram similarity when an AND query returns nothing.

### 3.2 Cold start has no floor, and the ceiling is one tag

`GET /recommendations` returns `[]` when a user has no signals — no popularity fallback, no trending,
nothing ([discovery.py:616-617](app/api/discovery.py:616)). The README describes laddering from
*"show me the popular stuff"* → *"what's like the things I clicked"* → *"variety"*; **the first rung
isn't implemented.** (A popularity+freshness ranker already exists — in `scripts/export_digest.py`,
offline only.)

At the other end, results are filtered to `vibe_score > 0 or matched_tags`, so **an event with no tag
overlap is dropped no matter how popular or close or free it is** — which permanently excludes the
265 untagged events, including all 183 free Funcheap listings. And the vibe component saturates at
100 from a *single* match, which is why one junk `#comedy` tag produced an all-comedy feed.

Also worth knowing: **all 1,578 events were ingested on the same day**, so the freshness term (15% of
the score) is currently a constant and contributes zero discrimination.

### 3.3 There is nowhere to learn about an event

There is **no `GET /events/{id}` and no event detail page.** The card title is a bare `<h3>` that
links nowhere; the only outbound link is "Tickets" → the external site. The full description is
never readable — it's `line-clamp-3` in the single place it renders, with no expand.

Fields the API serialises that **no UI surface ever renders**: `price`, `currency`, `end_at`,
`categories`, `status`, `distance_miles`, `organizer_name`, `attendee_count`, `is_free`,
`location_confidence`.

For community discovery this is fatal: the detail page is exactly where "who runs this / how often /
is it for beginners / what does it cost" would live.

### 3.4 Preferences are permanent and invisible

- Signal weights are all **strictly positive** (click 1.0, save 5.0, ticket-click 10.0, onboarding
  6.0, like 4.0); `record_signal` refuses to write anything with weight ≤ 0, so a negative signal
  **cannot** be recorded even internally.
- `preferred_vibes` and `saved_event_ids` are **append-only**. No `dislike`, `unsave`, `mute`, or
  `hide` action exists. **No code in `app/` ever deletes a database row.**
- There is **no profile or settings page** — nowhere to see, edit, or clear your vibes.
- On a card, tags are rendered as buttons whose only function is to permanently "like" that tag. A
  curious click is irreversible.
- Folder up/down votes exist but **provably never reach the recommender** (`app/api/social.py` doesn't
  import `UserSignal`).

Someone exploring a new hobby needs to be able to say "not that" and "I'm done with that phase."
Today the profile only accretes.

---

## Part 4 — Worth fixing cheaply

- **Mobile.** No hamburger, drawer, or disclosure of any kind — the nav just wraps. On a 375px
  viewport the search box + 13 filter chips + view toggle consume the entire first screen before one
  event appears. Only 13 responsive utilities exist in the whole frontend, and Playwright runs a
  single desktop project, so nothing tests it.
- **Dates read like a database dump:** `8/13/2026, 9:00:00 AM` — raw `toLocaleString()`, seconds and
  all. `"Thu, Aug 13 · 9:00 AM"` is the same one-line change.
- **"Viewed" is instrumentation wearing a button.** Users don't press "Viewed." Track it on card
  impression or drop it.
- **`/admin/sources` needs no authentication** of any kind — client or server. Anyone with the URL
  sees operational ingestion status.
- **Orphan routes:** `/onboarding`, `/admin/sources`, and `/concierge` have zero inbound in-app links.
  `/` has none either — the header is not a link, so **once you're in the app there is no way back to
  the landing page.**
- **No return-URL anywhere.** A logged-out invite recipient who clicks "Sign in" lands on `/explore`
  and the invite token is lost.
- **`/explore` is the only data-fetching route with no visible error state** — a failed fetch is
  swallowed to `console.error` and renders as "No events found. Try adjusting your filters."
- **Folder role dead-ends:** members see owner-only "Generate share link" / "Add" buttons that can
  only 403, because `FolderDetailResponse` carries no owner or role field. Revoking an invite doesn't
  remove members or rotate the public token.
- **Accessibility:** one `aria-live` region in the whole app (on a copy button), no skip link, no
  `sr-only` text, page-level filter chips have no focus styling, the admin table can't scroll
  horizontally inside its `overflow-hidden` card.

---

## Suggested order

| # | Change | Why first |
|---|---|---|
| 1 | Send structured tags from the vibe picker | Few lines; repairs the whole cold-start path |
| 2 | `tags` → `jsonb` + GIN + `@>` | Un-500s the only tag filter; prerequisite for real faceting |
| 3 | Server-side category filter, chips built from data | Turns the most visible dead end into working navigation |
| 4 | Suppress directions from low-confidence points | Trust bug; users get sent to the wrong city |
| 5 | `Series` entity + collapse repeats in Explore | Recovers 35.7% of the feed; the community object arrives |
| 6 | Organizer end-to-end (Meetup fields, client type, tsvector) | Makes "who runs this" real |
| 7 | Event detail page + `GET /events/{id}` | Where community context lives |
| 8 | Follow a group | The missing verb |
| 9 | Cold-start popularity fallback; drop the tag-overlap filter | Feed stops being empty or monotone |
| 10 | Community sources (Meetup working, makerspaces, leagues) | No ranking fixes an absent catalogue |
| 11 | Negative signals + profile page | Exploration needs an undo |
| 12 | Mobile nav + date formatting | Cheap, felt on every screen |

---

## Still unknown

- **Why Meetup, Reddit, and Eddie's List returned zero rows** `[ASSUMED: credentials/API access, not
  connector logic — all three have passing unit tests against fixtures. Decides whether 2.4 is a
  config fix or a rewrite. Settled by: a worker run with debug logging, or `/health/sources`
  history.]`
- **Whether Meetup's API terms permit storing group identity and membership counts** `[ASSUMED:
  permitted for display. Shapes how much of 2.2 is legally available. Settled by: the current Meetup
  API terms.]`
- **Whether the intended audience is "tourist planning a night out" or "resident building a life"**
  `[ASSUMED: the prompt's framing means the latter is wanted. The existing planner prompts are all
  date-night / bar-crawl / out-of-town-guests, so this is a genuine repositioning, not just a
  feature. Settled by: you.]`
- **Real-user behaviour** — every signal table is empty in this environment, so popularity is
  uniformly zero and I could not observe the recommender under load. `[ASSUMED: current ranking
  behaviour generalises. Settled by: production signal data.]`

---

*Method note: recon ran first and its gate would normally stop here for a "is this enough ground to
design on?" check. I carried on to the proposals because that's what was asked for — but the verified
facts are kept separate from the proposals so you can audit the reasoning, and every assumption the
proposals rest on is listed above rather than absorbed silently.*
