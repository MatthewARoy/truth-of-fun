# Proposal: Agentic Truth of Fun

**Status:** proposal (July 2026)
**Goal:** let a user define standing objectives ("more live music and comedy", "interesting date ideas") and have the platform — or an AI agent using it — preemptively propose activities, plan on the user's behalf, and alert on time-sensitive moments (tickets on sale, just announced, happening soon).

---

## 1. The target experience

Matthew tells the platform (or tells Claude, which tells the platform):

> "I want to go to more live music and comedy — say twice a month — and I want interesting date ideas."

From that point on:

- A **proposals inbox** fills with concrete, honest suggestions: *"Comedy night: {show} at Punch Line — matches your objective on #Comedy, #StandUp. First seen by Truth of Fun 2 days ago (source: ticketmaster). $25."* Date-idea objectives arrive as sequenced itineraries (drink → show → late-night snack), built by the existing concierge sequencer.
- **Time-sensitive alerts** fire when they matter: tickets for a watched artist go on sale, a matching event is newly announced, a saved event is postponed or cancelled, something on the calendar starts tomorrow.
- **Claude can act on his behalf**: from Claude Code/Desktop (or a scheduled agent), query events, check "anything new for me?", build and save a plan, adjust an objective — with a scoped, revocable token, never his password.
- **Progress is visible**: "2 live shows/month — you've been to 1, 1 more on the calendar."
- Accepting a proposal feeds the recommender; declining finally teaches it something too (today the platform has no negative-feedback channel at all).

## 2. Where the platform stands today

The examination (six subsystem deep-dives, findings verified against source) shows the foundations are unusually good — and the gaps are specific and closable.

### Strengths to build on

| Existing mechanism | Where | Why it matters here |
| --- | --- | --- |
| Rich event query API: full-text (tsvector+GIN), PostGIS radius, time presets, price/status, pagination | `app/api/discovery.py:246-341` | Already most of an agent's `search_events` tool |
| Concierge: NL in → structured itinerary out (LLM intent parse + deterministic 3-stop sequencer, 30-min buffers) | `app/api/discovery.py:531-608`, `app/services/concierge.py:80-122` | Already the shape of an agent planning tool; just fire-and-forget today |
| Recommender is a pure function (vibe 50 / popularity 25 / freshness 15 / diversity 10) with per-component scores on `ScoredEvent` | `app/services/recommender.py:20-27,40-94` | Reusable from a background loop, not just HTTP; explanation data already computed (then discarded at the API boundary) |
| Behavioral signals with weights + 30-day half-life decay | `app/models/user_signal.py`, `app/services/user_profile.py:54-61` | The feedback substrate for proposal accept/decline; `signal_type` is a free varchar — new types need no migration |
| Folders with unguessable `share_token`, invites, votes | `app/models/social.py:16-18`, `app/api/social.py:388-405` | The proven pattern for shareable, reviewable artifacts |
| Worker → API cross-process signaling via a DB table (`source_health`), unioned into `GET /health/sources` | `app/models/source_health.py:8-12`, `app/api/health.py:19-75` | The established pattern for every new background product (changefeed, notifications, evaluator health) |
| Scoped machine-JWT framework (HS256 or OIDC/JWKS) with `require_internal_scope` | `app/core/security.py:90-128,209-220` | Precedent for non-human callers; currently wired only to `/internal/secrets/*` |
| Typed TS client used by the web app with zero extra logic | `packages/api-client/src/client.ts` | An MCP server wraps ~15 methods and inherits the whole contract |
| Pluggable LLM seams (`IntentParser`, `VibeTagger`, `OnboardingTagExtractor` Protocols) with graceful no-key degradation | `app/services/concierge.py:182-184`, `app/services/vibe_tagger.py:11-13` | The pattern to clone for an objective compiler |
| Ticketmaster incremental sync via `modifiedDate` | `app/ingestion/ticketmaster.py:140-148` | "Changed at source since last run" already isolated |

### The seven gaps that block the target experience

1. **No agent auth.** The only user credential is a password-derived 7-day JWT; an agent would have to hold the password and re-login weekly. No API keys, no scopes for discovery/social, no delegation, no revocation surface.
2. **On-sale data is dropped at ingest.** Ticketmaster's `sales` block (`sales.public.startDateTime/endDateTime`, presales) is never read (`_map_ticketmaster_event`, `app/ingestion/ticketmaster.py:208-271`), and `_normalize_status` (`ticketmaster.py:323-331`) destroys the signal it does read: `offsale→cancelled` (wrong — off-sale events still happen) and `postponed→scheduled` (wrong — `postponed` exists in the status lifecycle). "Tickets just went on sale" is currently *unrepresentable*, even though the API response contains it.
3. **No change feed.** Every new/changed event passes through one choke point — the insert-vs-update branch of `DataPipelineService.process_raw_events` (`app/services/data_pipeline.py:39-53`) — and the field-level diff is already half-computed by `has_significant_new_information` (`:108-151`), then thrown away. Only aggregate counts survive. "Just announced" has data (`events.created_at`) but no emission mechanism, and no API filter exposes it (no `created_since` param, no `GET /events/{id}` at all).
4. **No standing-intent storage.** User taste is a flat hashtag list (`users.preferred_vibes`) plus decayed signals. No objectives, no watches/saved searches, no notifications tables. Preference capture is one-shot at onboarding with no edit surface.
5. **Nothing runs proactively per user.** All intelligence services are invoked only inside request handlers. The single background process (the 6-hour ingestion worker) never touches the recommender or any user. The only push channel is one global ops webhook.
6. **Plans are ephemeral.** `/concierge/itinerary` returns and forgets; folders store bare event IDs + votes — no ordering, status, rationale, or provenance. There is nothing an agent can write a plan *into* and nothing a user can accept or decline.
7. **No negative feedback.** `InterestAction` has no dismiss/unsave; `SIGNAL_WEIGHTS` is all-positive; and `record_signal` silently drops any weight ≤ 0 (`app/services/user_profile.py:119-121`). A proposal loop cannot learn from rejection.

### What Claude can do *today*, with zero changes

Worth stating because it anchors the roadmap: an agent can already call `GET /events` (unauthenticated, expressive filters), `POST /concierge/itinerary` (NL in, itinerary out, unauthenticated), register/login for a JWT, write save/like signals, read `GET /recommendations`, and stage event collections into folders with shareable links. What it *cannot* do: hold durable safe credentials, see event detail or "what's new since X", know about on-sale timing, persist a real plan, register standing intent, or get notified about anything.

---

## 3. Architecture: four workstreams

Everything below extends existing mechanisms — the worker loop, the pipeline choke point, the `source_health` DB-signaling pattern, the recommender's pure scoring function, the folder token pattern — rather than introducing schedulers, queues, or new runtimes. All API changes are additive, per the contract policy (`docs/api-contract-v1.md:468`); `docs/api-contract-v1.md` and `tests/test_api_contract_v1.py` must be updated in the same PR as each endpoint.

### Workstream A — Agent access layer

**Auth: scoped Personal Access Tokens, not OAuth (yet).** A new `agent_tokens` table (user_id, name, `token_prefix` indexed, SHA-256 `token_hash`, JSON `scopes`, expiry/revocation/last-used, request_count mirroring the `api_key_usage_snapshots` metering pattern). Token format `tof_pat_<prefix>_<secret>` — greppable, constant-time compare. Minting/listing/revoking is user-JWT-only (`POST/GET/DELETE /users/me/tokens`); an agent can never mint tokens, change credentials, or touch `/internal/secrets/*`. OAuth device flow is deferred until a remote (claude.ai connector) deployment exists.

A single `Actor` dependency in `app/core/security.py` accepts user JWT *or* PAT and carries `kind` + `scopes`; existing routes migrate from `get_current_user` to `get_actor` + `require_scope(...)` mechanically (interactive users get implicit `*`). Scopes: `events:read`, `profile:read`, `signals:write`, `plans:read/write`, `objectives:read/write`, `watches:read/write`, `notifications:read`.

**Provenance (project principle):** every write records the actor — `created_via` on `user_signals` and all new tables (`'user'` or `'agent:{token_id}'`). Agent-written signals count at full weight but stay permanently distinguishable; the UI can badge "saved by your agent", and any future discount is a query change, not a migration.

**API hardening for tool use** (all additive, in `app/api/discovery.py`):
- `GET /events/{event_id}` — the single worst gap for agents. Full detail: everything in `EventResponse` plus `first_seen_at` (honest rename of `created_at` in the payload — it's when *we* saw it, not when it was announced), `updated_at`, `source_name`, `source_tier`, `on_sale_at`/`ticket_status` (Workstream B), `location_confidence`, and recent changes.
- `GET /events` new params: `created_since`/`updated_since` (the "newly announced" poll primitive), `tags_any`/`tags_all` (replacing the single-`vibe_tag` limit), `categories`, `max_price`/`is_free`, `ticket_status`, `sort_by=newest`. Add an `X-Total-Count` header so agents know when to paginate without changing the body shape the web app expects.
- `GET /users/me` — profile read (preferred_vibes, saved ids, and the decayed `vibe_scores` map that `compute_vibe_scores_for_user` already computes and discards).
- `score_breakdown` on `GET /recommendations` — the per-component data already on `ScoredEvent`. "Why we propose this" is table stakes for an agent relaying suggestions to a human.
- Idempotency: `Idempotency-Key` on plan creation; saves skip duplicate signals; objective dedupe on `(user_id, lower(title))` → 409. Agents retry; the API must tolerate it.
- Rate limiting (slowapi): per-token limits on authenticated routes; per-IP limits on the two unauthenticated cost sinks — `POST /concierge/itinerary` (one Claude call per request) and `POST /auth/register`. This is a prerequisite for any public exposure, agent traffic or not.
- OpenAPI hygiene: version, `operation_id`, one-line descriptions on every route (~25 lines of FastAPI kwargs) — what MCP clients and codegen key on. Fix the known api-client drift (`EventsQuery` missing `include_past`/`status`; `EventResponse` type missing four server fields) since the MCP server builds on this package and drift becomes agent-visible lies.

**MCP server: `packages/mcp-server/`, TypeScript, wraps HTTP via the existing `packages/api-client`.** It does *not* import `app/services/` directly: auth/scoping/rate-limiting/provenance are enforced in FastAPI dependencies, and a service-layer MCP would bypass all of them and fork the contract (the OpenAPI schema is the declared source of truth). Topologically, a stdio MCP runs on the user's machine next to Claude Desktop/Code — it can reach the API, not Postgres. Config: `TOF_API_URL` + `TOF_TOKEN` (a PAT). Stdio transport first; the `@modelcontextprotocol/sdk` serves Streamable HTTP later from the same tool registrations.

Hand-curated tools (not OpenAPI auto-mount — 25 raw REST ops make a noisy toolbox), with `readOnlyHint`/`idempotentHint` annotations:

| Tool | Backed by |
| --- | --- |
| `search_events` (query, tags, categories, time window, geo, price, `created_since`, sort) | `GET /events` |
| `get_event` | `GET /events/{id}` |
| `get_my_profile` | `GET /users/me` |
| `get_recommendations` (with `score_breakdown`) | `GET /recommendations` |
| `build_itinerary` (query, `persist?`) | `POST /concierge/itinerary` |
| `create_plan` / `list_plans` / `respond_to_plan` | plans API (Workstream D) |
| `create_objective` / `update_objective` / `list_objectives` | objectives API (D) |
| `create_watch` / `list_watches` | watches API (C) |
| `get_updates` (since, unread_only) | `GET /notifications` — the agent's "anything time-sensitive for me?" poll |
| `get_changes` (cursor) | `GET /changes` — raw changefeed for stateful agents |
| `save_event`, `record_feedback` (like/dismiss/attended/unsave) | `POST /users/me/interests` |
| `get_platform_status` | `GET /health/sources` — agents qualify freshness claims |

Tool descriptions encode the honesty rules ("`first_seen_at` is when this platform first ingested the event, not its announcement date") and every result carries `external_url` so agents cite sources — consistent with the responsible-scraping "link back" norm.

### Workstream B — Capture time-sensitive data + a changefeed

**New `events` columns** (nullable; null when the source provides nothing — never inferred):

| Column | Source | Rule |
| --- | --- | --- |
| `ticket_status` | raw sales state (`onsale`/`offsale`/`presale`/`postponed`/`rescheduled`/...) | pass-through, untouched |
| `on_sale_at` / `off_sale_at` | Ticketmaster `sales.public.startDateTime`/`endDateTime` | TBA/TBD flags → null |
| `announced_at` | only true source publication times (Reddit `created_utc` today, already parsed at `app/ingestion/sources/reddit.py:147-148` — note that parse currently falls back to `utc_now()` when the field is missing; the fallback must **not** feed `announced_at`) | **never** backfilled from `created_at` |

`created_at` stays "first seen by Truth of Fun" and must be labeled that way everywhere. Two distinct facts, two distinct columns — the no-fabricated-dates principle applied to time-sensitivity.

**Ticketmaster fixes:** map the `sales` block in `_map_ticketmaster_event`; fix `_normalize_status` so `offsale` no longer becomes `cancelled` and `postponed` survives as `postponed`, while the raw code passes through as `ticket_status`. Thread the new fields through `contracts.py` (`OffersModel` gains the ticket fields, `SourceMetadata` gains a new `published_at`, and `to_legacy_event_payload` emits them — the one-function boundary where per-source `ingested_at`/`last_seen_at` currently die) and the pipeline merge (lower `source_tier` owns ticket fields, matching the existing time-ownership rule).

**Changefeed: append-only `event_changes`, written inside the same transaction as the event upsert** at the pipeline choke point. Not an in-memory diff handed to a notifier: API and worker are separate processes (the exact reason `source_health` exists), a pollable feed needs durable rows, and same-transaction writes mean a change row and its event mutation commit or roll back together. Columns: bigserial id (the poll cursor), event_id, `change_type`, verbatim `old_value`/`new_value` JSON, `source_name` (provenance), `observed_at`, `processed_at`.

Change vocabulary, deliberately narrow: `created`, `time_changed` (>30 min — the threshold `has_significant_new_information` already uses), `status_changed`, `ticket_status_changed`, `on_sale_at_set`, `price_changed`. **Deliberately excluded:** tag/category/description diffs (LLM-generated tags are merged into the payload before the diff, so tag changes would conflate LLM inference with source fact) and any "selling-out risk" signal (no source provides inventory; the honest proxy is `ticket_status` flipping to `offsale` before `start_at`, rendered as "no longer on sale via {source}", never "sold out").

**Prerequisite dedupe fix:** `_find_existing_event` (`app/services/data_pipeline.py:83-106`) must try exact `(source_name, source_event_id)` first, falling back to the fuzzy ±2h/85%-title match. Today an event rescheduled by >2h re-inserts as "new" — which would poison the `created` feed with false positives. The column is already stored and indexed.

Pure `diff_event()` in a new `app/services/change_detector.py` (unit-testable without a DB); emission in the insert/update branches of `process_raw_events`.

### Workstream C — Watches, notifications, delivery

**`watches`** — one table, two kinds. `watch_type='event'` (on-sale/status/price for a specific event) or `'query'` (criteria JSON whose keys **mirror `GET /events` params exactly** — one filter language everywhere; artist/venue watches are just query watches against the existing tsvector index). Fields: user_id, `created_by` (`user`/`agent`), `objective_id` nullable (objectives materialize their criteria as watches they own), `triggers` (subset of change types plus two time-derived ones), `lead_time_minutes`, `channel` (`in_app`/`webhook`), `webhook_url`, `max_notifications_per_day`, `is_active`.

`on_sale_opening` and `starting_soon` are **time-derived triggers**: they fire when the clock crosses a *source-provided* timestamp (`on_sale_at`, `start_at`), computed by sweeps that mirror the existing `_mark_past_events` pattern — honest because the underlying timestamps are never inferred.

**Implicit watches:** saving an event and accepting a plan auto-create an event watch (`created_by='system'`) with the safety triggers — `status_changed`, `ticket_status_changed`, `starting_soon` — so "your saved show was postponed" and "tomorrow: the plan you accepted" work without the user ever discovering the watch feature. They're listed and deletable like any watch, and removed when the event is unsaved or the plan declined.

**`notifications`** — user_id, watch_id/event_id/`change_id` FKs (full provenance chain: notification → change → verbatim old/new → source), trigger, templated title/body (**no LLM in the alert path**), payload JSON, `dedupe_key` UNIQUE, read/delivered timestamps, delivery_error.

**Anti-spam rules (opinionated):**
1. Idempotent inserts: `dedupe_key = watch:event:trigger:value_fingerprint`, `ON CONFLICT DO NOTHING` — re-observing a state can never double-notify; a genuinely new price still gets through.
2. One notification per (watch, event) per cycle — changes grouped ("Price dropped to $35 and tickets are now on sale").
3. Daily cap per watch, except cancellation/postponement which always delivers (safety-relevant, low volume).
4. `created`-flood control on fresh query watches: max 5 individual notifications per cycle, remainder rolled into one "12 more new comedy events" summary.

**Evaluation** (`app/services/watch_evaluator.py`, called from `run_once` after the pipeline commit): claim unprocessed `event_changes`, join event watches by id, and for query watches re-run criteria scoped `WHERE events.id IN (:changed_ids)` — reusing the filter-building logic from `GET /events`, factored into a shared `apply_event_filters()` helper so watch matching and the public API can never drift.

**Cadence without touching the 6-hour ingest:** refactor `run_forever` into a tick loop — every `fast_tick_seconds` (default 900) run the two time sweeps + evaluator (cheap, DB-only); full ingestion still only when the 6h interval elapses. Phase 4 adds targeted refresh: for Ticketmaster events with active watches, refetch by id (`GET /discovery/v2/events/{id}`, new `fetch_event_by_id`, existing rate limiter), capped per tick, fed through the normal pipeline so change detection stays uniform. On-sale moments stop being invisible inside a 6-hour window exactly where someone cares.

**Delivery:** in-app first (zero new dependencies — the notifications table *is* the inbox, served by `GET /notifications` + bulk mark-read). Per-watch webhook for agents (generalize `alerting.py` with `send_webhook(url, payload)`; the global ops webhook stays ops-only). Webhook URLs are validated at watch creation: HTTPS only, public hosts only (reject loopback/private/link-local ranges — the worker must not be an SSRF proxy), and every delivery carries an HMAC signature header derived from a per-watch secret returned once at creation, so receivers can authenticate the platform. `GET /changes?since_id=` gives stateful agents a cursor feed with no server-side per-agent state. **Email is explicitly deferred** — no sending dependency exists (IMAP is inbound-only); don't fake it, add it when an SMTP/provider decision is made, behind a `deliver_proposal_batch()` seam.

### Workstream D — Objectives & proactive proposals

**Objectives: raw natural language + an LLM-compiled structured spec, both persisted.** The NL text (`raw_text`) is the source of truth the user edits and is never rewritten; the structured fields are what the matcher executes. Every LLM-filled field is recorded in `inferred_fields` with `compiled_model` — the honest-provenance principle extended to user intent, and it powers a "We read this as: … [edit]" correction UI.

Key fields: `objective_type` (`recurring` — cadence-driven, "2 live shows/month" — or `discovery` — open-ended, "interesting date ideas"), `match_tags`/`match_categories`/`match_query` (tsvector arm), `cadence_target`+`cadence_period`, `budget_max`, geography (`geography_label` ILIKE string, or `center`+`radius_miles` **only from an explicit user-provided location — never LLM-geocoded**), `preferred_days`, `status`, `created_via`, `last_evaluated_at`.

**Compiler** (`app/services/objective_compiler.py`): clone the proven `ClaudeIntentParser` pattern — Protocol seam, Haiku, JSON-schema prompt, None-on-failure. **LLM runs once at create/edit; matching is deterministic SQL + the pure recommender.** This caps LLM cost independent of user count and cycle frequency. Keyless fallback is deliberately conservative: the heuristic tag extractor produces junk from short objective text ("#More", "#MoreLive"), so without an API key objectives compile to `match_query`-only and evaluate **on demand only** — no proactive generation of noise every 6 hours.

**Matcher** (`app/services/objective_matcher.py`): one SQL pass per objective — upcoming scheduled events, OR-union of (tsvector match ∪ tag overlap ∪ category overlap), AND-filtered by budget/geography/days; incremental fast path on `created_at OR updated_at > last_evaluated_at` (updated_at matters: events get rescheduled *into* scope). Candidates scored by blending objective fit with the untouched `RecommenderService.score_events`. Honest caveats: `tags`/`categories` are plain JSON (not JSONB, no GIN), so multi-tag matching is partly sequential-scan + Python — fine at pre-public scale, revisit with JSONB+GIN if corpus growth demands. The budget filter must decide the NULL-price policy explicitly (include unknown-price events, disclosed in the rationale as "price unknown") since most scraped events carry no price.

**Plans: one artifact for everything proposable.** The examination produced two overlapping concepts (agent-written "plans" and engine-generated "proposals"); this proposal unifies them into a single `plans` + `plan_items` pair:

- `plans`: user_id, `origin` (`objective`/`agent`/`concierge`/`user`), `objective_id` nullable, `kind` (`event`/`itinerary`), title, `rationale` + `rationale_source` (`template` now; `llm:{model}` later — provenance), `status` (`proposed`/`accepted`/`declined`/`snoozed`/`archived`/`expired`) + `snoozed_until`, `share_token` (folder pattern reuse), `created_via`, `idempotency_key`, timestamps.
- `plan_items`: plan_id, event_id, position, `role` (**exactly the sequencer's kinds — `main_event`, `pre_event_drink`, `late_night_snack`, plus `single`** — so the planner UI's rendering maps 1:1), `match_score`/`matched_tags` snapshot (legitimately point-in-time facts), optional note. **No snapshot of event title/time/price** — items join live `events` rows so a rescheduled event never shows a stale date, and **no free-form times** — an agent cannot write a fabricated schedule into the platform. Expiry is computed against live `start_at` at sweep time, not stored at creation (a stored `expires_at` is itself a stale snapshot).

The **proposals inbox** is simply `GET /plans?status=proposed`. Concierge persistence: `POST /concierge/itinerary` gains optional `persist: true` (authenticated + `plans:write` only) → returns `plan_id` + `share_url`.

**Generator** (in `run_once`, right after `_mark_past_events`, plus a synchronous `POST /users/me/objectives/{id}/evaluate` that ships user-visible value before any worker changes and doubles as the agent's "evaluate now" tool):
- Recurring objectives → single-event plans; discovery objectives → itinerary plans: top-scored candidate becomes the anchor (fixing the concierge's current earliest-event-wins weakness), support events via the tier≥3 `ST_DWithin(0.5mi)` query extracted from the route into `concierge.find_support_events()` so route and generator share it. No support events → degrade to a single-event plan rather than fabricate stops.
- Anti-spam caps in config: max 2 proposals/objective/cycle, max 6 open per user; dedupe against prior plan items and saved events; objectives already on pace this period are skipped — **cadence throttling and progress tracking are the same computation**.
- Rationale is template-generated from real columns only (matched tags, `first_seen`, source_name, people-interested count, price/venue) — explainable, free, honest by construction.
- Evaluator health: upsert a `source_health` row (`source_name='objective_evaluator'`) — it surfaces in `GET /health/sources` with zero API changes (DB-backed health, per project principle).

**Feedback loop** (`POST /plans/{id}/respond`): accept → `plan_accepted` signals + events added to saves; accepted itineraries optionally materialize into a folder (factor the folder-create/add-item logic out of route handlers into the service layer first); decline → `plan_declined` (−4.0) per matched tag; snooze → resurfaced by the worker. **Enabling negative signals is a three-site fix, not a flag:** `record_signal` drops weight ≤ 0 at write (`user_profile.py:119-121`), `compute_vibe_scores_for_user` skips non-positive contributions at read (`:94`), and `_vibe_score` needs a floor once sums can go negative (`recommender.py:116-131`). The 30-day half-life then makes decline-bursts fade instead of permanently killing a vibe. New `attended` signal (weight 12.0, "I went" button) so progress counts real attendance; the UI must never label an unattended acceptance as "been to" — copy reads "1 attended, 1 on the calendar".

**Web surfaces:** `/objectives` (create with "we read this as" chips, progress bars, pause/edit), `/proposals` inbox (accept/snooze/decline, reusing the planner's stop rendering), nav bell + unread count (the admin page's existing 30s polling pattern), "Watch this event" on cards, "Save this search as a watch" on explore, and a "Connected agents" settings page (PAT list/mint/revoke — the consent surface).

---

## 4. Unified data model (new tables)

| Table | Workstream | Purpose |
| --- | --- | --- |
| `agent_tokens` | A | scoped, hashed, revocable PATs |
| `event_changes` | B | append-only changefeed, cursor for agents, provenance chain |
| `watches` | C | event + query subscriptions, user- or agent- or objective-owned |
| `notifications` | C | the alert inbox; dedupe_key idempotency; change_id provenance |
| `objectives` | D | raw NL + compiled spec + inferred_fields provenance |
| `plans` + `plan_items` | D | unified proposals/itineraries/agent plans; live event joins, no fabricated times |

Plus four nullable columns on `events` (`ticket_status`, `on_sale_at`, `off_sale_at`, `announced_at`) and `created_via` on `user_signals`. All migrations chain on the current head `202606130001_add_folder_invite_expiry` (verified — not `67ae74b20ec1` as one early draft assumed).

## 5. How an agent actually uses it

**Interactive ("plan Saturday"):** Claude Desktop with the MCP server configured → `get_my_profile` + `list_objectives` → `search_events(tags_any=[#DateNight], time_preset=this_weekend)` or `build_itinerary("date night in the Mission Saturday", persist=true)` → user gets a share URL and the plan sits in the inbox as `proposed`, provenance `agent:{token}`.

**Scheduled steward (cron/Claude scheduled task, e.g. Monday 9am):** `get_updates(since=last_run)` → anything urgent (on-sale opening, cancellation) gets surfaced immediately; then `list_objectives` → for behind-pace objectives call `evaluate` or `search_events(created_since=last_run, ...)` → `create_plan` with rationale → optionally `create_watch` on high-interest events that aren't on sale yet. Everything the agent creates is visible, badged, and revocable in the web UI.

**Platform-only (no external agent):** the same outcome arrives via the worker's evaluation step and the in-app inbox/bell — the agent is an *optional* enhancement, not a dependency. This is the key architectural property: **objectives, watches, plans, and notifications are platform primitives; Claude is one client of them.**

## 6. Roadmap

**Phase 1 — the corpus becomes time-aware, and agents can see (ship first: data only accrues from deployment day).**
Migrations (events columns, `event_changes`, `agent_tokens`, and `user_signals.created_via` — provenance must exist before the first agent write, since PATs get `signals:write` immediately); Ticketmaster `sales` mapping + `_normalize_status` fix + contracts threading; source_event_id-first dedupe; changefeed emission; `GET /events/{id}` + the new `GET /events` params from §3A + `X-Total-Count`; `GET /users/me`; `GET /changes`; PAT auth + `get_actor` migration + token endpoints; slowapi on concierge/register; OpenAPI hygiene + api-client drift fix; MCP server with the read tools (`search_events`, `get_event`, `get_my_profile`, `get_recommendations`, `get_changes`, `get_platform_status`) plus `build_itinerary`, `save_event`, `record_feedback`.
*Outcome: Claude (locally, with a PAT) can answer "what comedy shows were announced this week?", "what goes on sale soon?", and "plan my Saturday" — before any proactive machinery exists.*

**Phase 2 — write-back and standing intent.**
`plans`/`plan_items` + router + concierge `persist`; `objectives` + compiler + matcher + CRUD + synchronous `/evaluate`; MCP tools `create_plan`/`list_plans`/`respond_to_plan` and `create_objective`/`update_objective`/`list_objectives`; negative-signal three-site fix + new signal weights (`dismiss`, `plan_accepted`, `plan_declined`); `/objectives` page, proposals inbox page, "Connected agents" page.
*Outcome: "more live music and comedy" typed once, evaluated on demand, results accepted/declined with learning; agents create durable, reviewable plans.*

**Phase 3 — the platform becomes proactive.**
Worker evaluation step + expiry sweep + evaluator health row; `watches` + `notifications` + evaluator + fast-tick refactor + time sweeps (with implicit watches, and a backfill that materializes watches for objectives and saved events created during Phases 1-2); webhooks for agent watches; MCP tools `create_watch`/`list_watches`/`get_updates` and the `attended` action on `record_feedback`; nav bell + `/alerts`; watch buttons; progress tracking; cadence throttling.
*Outcome: the full target experience — preemptive proposals every cycle, on-sale/announced/starting-soon alerts, progress bars — with or without an external agent.*

**Phase 4 — reach and polish.**
Targeted Ticketmaster refetch of watched events on the fast tick; digest email (after a provider decision); LLM-written rationale (provenance-marked); Streamable-HTTP MCP + OAuth for remote claude.ai connectors (requires a deployed, TLS-fronted API — currently single-box compose with no proxy); Ticketmaster sync state file → DB row; tag taxonomy/embeddings if lexical matching proves too coarse; JSONB+GIN on tags if scale demands.

## 7. Data-integrity guarantees (inherited principles, applied)

1. No fabricated dates or coordinates: `on_sale_at`/`announced_at` only ever copied from sources (TBA → null); `created_at` always labeled "first seen by Truth of Fun"; plan stops carry no free-form times; objective centers never LLM-geocoded.
2. Honest LLM provenance: `inferred_fields`+`compiled_model` on objectives; `rationale_source` on plans; LLM-tag diffs excluded from the changefeed; no LLM anywhere in the alert path.
3. No invented urgency: no "selling out" predictions (no source provides inventory); `offsale` before start renders as "no longer on sale via {source}".
4. DB-backed health: changefeed, notifications, and evaluator status all live in tables the API serves; `objective_evaluator` appears in `GET /health/sources` like any source.
5. Honest agency: every agent action badged via `created_via`; tokens scoped and revocable; agents can never touch credentials or token minting.

## 8. Cost, ops, and risks

- **LLM cost is bounded by design:** one Haiku call per objective create/edit, zero in the matching/alerting loops; concierge rate-limited per IP. Make the two hardcoded model ids env-configurable while touching this code.
- **Worker load:** evaluation and sweeps are DB-only; the known N+1 in `compute_vibe_scores_for_user` (per-signal `session.get(Event)`) is fine per-request but must be batch-loaded when fanning out across users per cycle.
- **Scale honesty:** JSON tag matching is partly sequential-scan; acceptable pre-public, measured before it matters.
- **Biggest external dependency:** on-sale data quality is Ticketmaster-only today; other sources contribute `created` (announcement) signals but no sales windows — alerts must degrade per-source honestly rather than pretend uniform coverage.
- **Open questions:** email provider choice (Phase 4); remote deployment story for claude.ai connectors (the API currently has no public endpoint); whether folder materialization of accepted itineraries should be automatic or a button (proposed: a button — folders imply sharing intent).
