# Reliability fixes, 2026-09-29

Implemented on `codex/review-fixes`, based on local `main` at `b6bcca2`.
The reviewed local baseline was 16 commits ahead of the GitHub baseline
`bdf444b`; this work does not publish, merge, or deploy those existing commits.

## Implemented

| Area | Result |
| --- | --- |
| Source identity and revisions | Persist trusted provider aliases and input hashes; apply cancellation, price, schedule, and venue revisions without replay oscillation. Weak calendar/title/recurring-slug identifiers stay within temporal matching. Conflicting venues prevent generic-title merges. |
| Location integrity | Coordinates and confidence move together; unchanged old-venue aliases cannot overwrite a relocation. City reaches the geocoder. Provider outages are retryable failures rather than long-lived cached misses. |
| Ingestion recovery | Completion metadata is acknowledged after successful persistence. Capped/failed/rejected fetches remain incomplete. The worker records failures and survives the next cycle; candidate extraction failures are visible. |
| Tagging cost | Cache descriptions with model/prompt identity across worker sessions. Bound descriptions to 8,000 characters and calls to 200 per run. Transient/disabled-provider failures remain retryable. Concurrent cache fills do not roll back unrelated events. |
| Discovery and planning | Exclude unavailable events by default, preserve ongoing events, share current-weekend windows, and avoid already-elapsed named-day windows. Multi-stop plans require published predecessor end times and a 30-minute buffer on the same outing night. Labels describe event order rather than inventing food/drink activities. Uncertain anchor coordinates produce one stop. |
| Preferences and ranking | Structured choices persist directly and can be replaced/cleared. Cold or unmatched profiles receive eligible fallback suggestions. More matching preferences and learned behavior can improve an existing score. The UI identifies scores as heuristic scores. |
| Recommendation work | SQL applies relevance, popularity, freshness, diversity, and pagination before hydrating a page. No earliest-N cutoff or arbitrary result-pool truncation. Profile scoring uses one streamed join instead of a per-signal event lookup. |
| Browser reliability | Separate draft/applied search, cancel superseded work, ignore stale responses, retry the failed page, show errors, debounce affected folder queries, clear personal content on logout, preserve safe invitation return paths, and render venue-local time. The subsequent sharing safeguards omit the original query from public links. |
| HTTP client | GET-only bounded transient retries with backoff, Retry-After, deadline, and cancellation. Writes do not retry. |
| Optional AAIM | Atomic usage/reset transitions preserve disabled keys. Failed Redis initialization retries. Health reads are read-only; API and worker usage sample only used keys, skip busy sampling locks, and bound retained history. |
| Release checks | Add client regressions, production web build, and real Redis/Postgres concurrency checks to CI. Browser tests own their loopback server. Update locked JavaScript dependencies to remove the reported advisories. |

## Validation of the initial reliability fixes

- Fresh Python installation from `uv.lock`: **568 backend tests passed**, no skips,
  using disposable PostgreSQL 16/PostGIS and Redis 7. The only warning is the
  dependency's existing `httpx` TestClient deprecation.
- Fresh npm installation from the updated lock: **30 browser tests passed** with
  pinned Chromium, plus **7 API-client tests**. Web lint/typecheck and MCP build passed.
- Production `next build --webpack` passed. Default Turbopack build encountered
  this host's internal CSS-worker port `EPERM`; CI retains the default production
  build. Browser tests use mocked or unavailable APIs, not a real authenticated
  browser-to-backend journey.
- Python and JavaScript dependency audits reported **no known vulnerabilities**.
- One local synthetic recommendation request over **10,000 events** with 2 KB
  descriptions returned 25 events, hydrated **25 Event objects**, and used
  **3 SQL statements in 202.7 ms**. Setup/rollback excluded; no concurrent load
  or production latency claim. Synthetic rows were rolled back.
- Alembic fresh upgrade and latest downgrade/upgrade passed. Legacy backfill
  preserves canonical events, seeds unique trusted identities, and leaves
  ambiguous/calendar identifiers unmapped. Durable alias revisions and cache
  reuse were also verified across real PostgreSQL sessions with fake providers.
- Independent code reviews found and corrected stale end times, coordinate-only
  revisions, cache-write races, stale venue coordinates, ranking-before-pagination,
  and telemetry acknowledgement/coverage defects.

No live provider requests, paid model calls, production data, deployment, or
external messaging were used for acceptance. These results are local validation;
hosted CI has not run for this branch.

## Migration and operational limits

Apply `alembic upgrade head` before running the new ingestion code. Migration
`202609290001` adds `event_source_records` and `vibe_tag_cache`. Downgrading removes
those derived records/caches; canonical events remain.

Ticketmaster Discovery does not document the previously assumed modified-date
filter. Completion metadata is now honest, but date-partitioned retrieval beyond
its 1,000-result page boundary is still needed for full coverage. Replaying a
capped search does not solve that coverage gap.

Legacy ambiguous identities require reconciliation; weak source identifiers
cannot safely recognize cross-date reschedules. The new alias/hash table is not
a full revision history or a merge-reversal system. Tagging limits are per run,
not fleet-wide quotas. Profiles still scan a user's history and PostgreSQL still
ranks the eligible catalog; hydration/query-count reductions are not a claim of
constant total work or production latency.

## Remaining product work

1. Date-partitioned Ticketmaster coverage and durable per-source observations,
   last-verified timestamps, correction history, and shared-plan freshness.
2. Saved-events view and unsave; negative feedback and ranking evaluation.
3. Account recovery/deletion/session revocation and folder membership/share revocation.
4. Structured planner constraints, stop editing, resolved geography, and travel
   estimates. The 30-minute buffer does not establish opening hours, reservations,
   accessibility, or transport availability.
5. Broader real browser/API/database acceptance and deployment verification. The
   subsequent sharing safeguards add a focused real sharing lifecycle CI job.

## Subsequent sharing safeguards

The user explicitly approved removing public prompts, requiring deliberate
publication, and adding expiry and owner revocation. The implementation and
rollout requirements are recorded in [Sharing safeguards](sharing-safety.md).
The earlier blocked MCP proposal is superseded: the implemented tool accepts
selected event IDs and bounded metadata, requires authenticated explicit public
publication, and never accepts the original planning prompt.
