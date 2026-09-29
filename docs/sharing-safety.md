# Sharing safeguards

Public itinerary links now expose selected event snapshots without the original
planning request. This also applies to legacy snapshots: their stored `query`
field is omitted from every public response and exported plan text. For backward
input compatibility, the API accepts but ignores `query`; new records store an
empty string. The TypeScript client excludes it when serializing requests.

## Explicit publication and ownership

Building a plan and copying its text do not create a public link. A signed-in
user chooses **Create public link**, with notice that anyone holding the link
can read the selected plan. The default expiry is 14 days, with browser choices
of 7, 14, or 30 days; the API accepts 1–30 days.

The **Shared plans** page lists the owner's links after navigation or reload,
including expired and revoked links. **Revoke link** permanently disables future
reads through that link. The owner API checks both authentication and ownership;
knowing another person's public token does not grant management rights.

Public reading remains anonymous. Unknown, malformed, expired, and revoked
tokens receive the same 404. Sharing routes use `Cache-Control: private,
no-store`; the browser also requests fresh data and rechecks on focus,
visibility changes, and expiry. An already open page is not remotely erased at
the instant of revocation, and downloaded or copied content cannot be recalled.

MCP exposes `share_itinerary`, `list_my_itineraries`, and `revoke_itinerary`.
Publication requires a signed-in user and `publish_publicly: true`; its
description limits use to an explicit user request for a public link. Its strict
schema accepts event IDs, ordering, travel buffers, bounded metadata, and expiry,
with no free-text prompt or private notes. Tool schemas cannot independently
prove a conversation contained consent; the calling agent must honor the tool's
instructions. Planning tools do not invoke publication.

## Migration and rollout

Migration `202609290002`, following `202609290001`, adds `expires_at` and
`revoked_at`. Existing links receive a **14-day grace period from migration
time**, regardless of their original age. Existing owners are preserved;
anonymous legacy links remain unowned and age out. Possession of a link does not
allow claiming its ownership. Legacy private queries remain in the database;
this change is public-data minimization, not a historical data deletion job.

Coordinate the migration and API release: old API processes do not write the
now-required expiry column, so they cannot continue creating links after the
migration. During rollout, pause creation or briefly stop old API processes,
apply `alembic upgrade head`, and start the new API. Release the matching client,
web, and MCP packages for the changed authentication and response contract.

Rolling back to old API code restores its old disclosure behavior and removes
its enforcement of expiry/revocation. Downgrading the migration drops lifecycle
columns while preserving itinerary rows. Neither is a privacy-preserving
rollback; keep public sharing disabled if reverting this release.

## Local acceptance

Completed on 2026-09-29:

- **582 backend tests passed**, including the real PostgreSQL migration and
  owner/public lifecycle checks and Redis concurrency checks. Four additional
  harness safety regressions passed after review identified PostgreSQL URL
  query parameters that could bypass a naive host/database check.
- **40 browser regressions, 10 API-client tests, and 8 MCP protocol tests
  passed**. Web lint and typecheck passed. Independent review caught and
  corrected the owner list retaining an Active label after expiry.
- The production `next build --webpack` passed. The generated standalone
  server passed the real browser/API/PostGIS sharing lifecycle below. This host
  previously hit a Turbopack CSS-worker port restriction; CI retains its default
  production build. Hosted CI and deployment have not been run for this branch.

Regression coverage includes authentication, legacy query omission, expiry
boundaries, ownership, idempotent revocation, cache headers, and real PostgreSQL
migration/lifecycle checks. Client and MCP tests exercise request serialization,
explicit publication, protocol validation, and empty 204 responses.

`npm run web:test:integration` runs the standalone production browser bundle against the
actual API and a disposable local PostGIS database, without intercepted API
requests. It signs up a user, builds a private plan, checks that planning caused
no publication, deliberately creates a link, reads it in an anonymous browser,
reloads the owner's management page, revokes the link, and verifies public 404.

Build with `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8168` first, and supply
`SHARING_E2E_DATABASE_URL` pointing to a local disposable database whose name
ends in `_test`. The test helper refuses other hosts/database names and URL
query parameters that could override connection settings. The
`web-ui-ci` workflow runs this test after the production build and browser
regressions. Local validation does not establish hosted CI or deployed behavior.
