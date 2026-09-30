# Scoped agent access acceptance — 2026-09-29

Issue #12 is bounded to the authentication layer. Owners can mint, inspect and revoke independently expiring credentials without giving agents their password. SHA-256 token hashes are stored; raw secrets are returned only once. Authenticated admissions increment durable counters atomically before scope checks, including forbidden attempts; invalid/revoked and rate-limited requests are not admissions.

Supported scopes are events:read, profile:read, signals:write and plans:read. Signal writes require profile:read as well because the existing response contains profile state. Interactive account actions, token management, public publication and folder mutations remain user-JWT only. This deliberately does not pre-authorize future plans:write operations. Historical signals receive legacy provenance, while new signals distinguish user and agent:<token id>.

## Validation

- Backend: 697 passed against a disposable PostGIS database and Redis. Includes negative authorization, hash-only storage, expired/deactivated owner, signal provenance, per-token rate limits, migration preservation and 24 concurrent admissions with durable counters.
- Real MCP client -> API -> PostGIS: read/search succeed; save and escalation fail; metadata shows usage without secrets; revocation blocks subsequent use. Existing real browser explicit-publication/revocation flow also passes (2 integration tests).
- Shared API client: 10 tests; MCP: 9 tests. Web lint, typecheck and default production Turbopack build pass.
- An initial full-suite run encountered a leftover jazz event from the separate browser harness in the same disposable database. Removing only that browser fixture restored the backend's expected count. Hosted jobs use separate fresh databases.

## Release boundary

Migration 202609290004 has been exercised only on the disposable local test database, including downgrade/upgrade preservation. Existing application databases have not been migrated. This is a merged-code acceptance record, not deployed or configured service evidence. Rate limits apply per API replica, as the current inbound limiter does; existing registration and concierge cost limits remain in place.
