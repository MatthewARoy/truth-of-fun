# Source diagnostics and published metadata, 2026-09-29

- 19hz retains the published comma-separated genres after `(City)` as category
  evidence and removes them from the venue. It emits no synthetic vibe tag;
  the existing bounded classifier can infer vibes when supported by inputs.
  Existing stored tags are not backfilled by this change.
- Every zero-result worker run logs and persists a diagnostic in the existing
  source-health fields. Disabled connectors, fetch exceptions, empty discovery,
  and rejected candidates remain distinguishable. Quiet results retain the
  existing degraded/consecutive-zero state machine; incremental no-change
  results remain successful. No additional source-health migration is needed.
- Meetup requires its token and conservatively rejects partial GraphQL data
  accompanied by errors, HTTP-200 GraphQL errors or incompatible
  response shapes. Eddie's List reports missing IMAP configuration and failed
  mailbox selection/search/fetch. Provider/mailbox behavior remains fixture-tested;
  this change does not configure either service or prove live coverage.
- With AAIM and Redis, the environment Ticketmaster fallback has a reserved,
  non-secret usage record. It stays outside the rotation inventory, is never
  used to bypass a configured disabled/exhausted inventory, and retains quota
  counts/status across instances. Atomic usage/reset behavior applies to it.
  Each HTTP attempt, including transient retries, is accounted for. If Redis
  is unavailable, the existing configured fallback remains possible but health
  explicitly reports unavailable shared telemetry instead of a missing key.
  Counters measure this application's requests; provider usage elsewhere is
  unknown. Replacing the environment credential does not reset its counter;
  the configured quota window supplies the reset.
- The README's stubbed source-health screenshot is labelled illustrative.

Fable 5.1 on 20x reviewed published head `44a9ea0`. Repairs keep disabled
configuration as a zero-result diagnostic without repeated per-cycle alerts,
refresh the environment quota cap atomically while preserving usage/disable
state, identify sender-allowlist rejection, timestamp zero-result diagnostics,
and exclude historical fallback telemetry from managed-inventory alert counts.
Tests cover these repairs and real Redis cap changes. An intermediate test
fixture reused a closed mock transport and attempted Ticketmaster with the fake
key `fixture`, receiving 401; client ownership now keeps both cycles mocked.

Validation uses disposable PostGIS/Redis and mocked provider responses. No
application database, ingestion run, deployment, or provider activation occurs.
