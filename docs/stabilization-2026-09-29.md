# Pending-work stabilization, 2026-09-29

The inventory found 14 worktrees, 17 local branches, and no open GitHub PRs.
GitHub had 15 merged PRs and one previously closed PR (#27). The remote main
baseline was `bdf444b`; local main at `b6bcca2` held 16 unpublished commits.

## Selected integration

- Retain the 16 main commits: published/estimated times, ongoing events,
  geocoding and confidence integrity, cache recovery, and concierge ranking.
- Integrate the eight `codex/review-fixes` commits through `7f8545f`: durable
  source revisions, bounded tagging and retries, ingestion recovery, ranking,
  browser request lifecycles, explicit authenticated public sharing, expiry,
  owner revocation, and real sharing acceptance in CI.
- Recover the dirty `exciting-meitner-22f01a` work: correct Ticketmaster offsale
  and postponed statuses, fetch undated postponements, retain listing identity
  across reschedules, and explain unavailable events on cards. The newer source
  identity pipeline supplies the identity and revision behavior; its tests are
  retained rather than replacing it with the older implementation.
- Recover the dirty `unruffled-goodall-fa6b05` work: bounded date-partitioned
  Ticketmaster retrieval, per-day/per-category calendar crawling, JSON-LD
  extraction, source category evidence, and comedy inference.
- Extract `513f733` navigation fixes: uncertain coordinates do not anchor
  nearby searches or directions when no venue/address is available.
- Correct integration defects: capped/repeated/failed crawls report incomplete
  coverage, completion waits for persistence, replay cannot revive an expired
  event without a schedule change, logout still clears event-card state, and
  ranking fixtures refuse non-disposable databases and URL overrides.

## Every branch disposition

| Branch | Disposition and reason |
| --- | --- |
| `main` | Integrate its 16 unpublished commits through the reviewed PR. |
| `codex/review-fixes` | Integrate all eight commits. |
| `claude/exciting-meitner-22f01a` | Recover dirty status/UI work; newer identity pipeline supersedes its pipeline rewrite. |
| `claude/unruffled-goodall-fa6b05` | Recover dirty bounded crawling/category work, repairing incomplete-fetch reporting. |
| `claude/quizzical-lewin-d8ffd2` | Extract navigation fixes; retain newer preference/category behavior. Archive old JSONB migration lineage and dynamic category-facet proposal for separate product work. |
| `claude/date-plan-event-review-500814` | Archive incompatible source-projection/offer rewrite. Its migration explicitly deletes all event rows, folder votes/items, and signal event references. The newer non-destructive source-identity/cache migrations cover the bounded reliability needs. Offer extraction/quarantine/projection remains separate work. |
| `claude/competent-meitner-c35508` | Archive sibling-database fixture that drops/rebuilds public schema and races between runs. Retain guarded transactional isolation and disposable test services. |
| `claude/frosty-golick-a29431` | Transactional ranking isolation is already in main; retain newer tests and add disposable-database checks. |
| `claude/sf-activities-sunday-b5799c` | PR #22 merged; rescued field-width protection already exists in the newer pipeline. |
| `claude/kind-mendel-1a2a80` | PR #2 merged; PR #5 supersedes rescued model-alias changes through centralized configuration. Archive old screenshots. |
| `claude/activity-categories-rebased` | PR #7 merged; archive stale alternate commit history. |
| `claude/live-readiness-obs-mcp` | PR #6 merged; current confidence-aware discovery/geocoding and tests supersede the stale fixed 0.9 threshold, which would exclude supported geocodes. |
| `claude/musing-fermi-8fb296` | Patch-equivalent to main's `9e4dfb9`; no new change. |
| `claude/happy-driscoll-600d51` | Keep `.superpowers/` ignore; do not ignore shipping Docker configuration files. |
| `claude/evening-itinerary-august-2-2fdbe0` | Archive local Docker override that skips Alembic and assumes incompatible dev schema; do not make it the default. |
| `claude/sf-comedy-shows-sunday-edc3ea` | Exactly main; no unique work. |
| `claude/tomorrow-events-date-ideas-43c41e` | Exactly main; no unique work. |

## Validation and release boundary

Use fresh locked Python/Node installations and disposable loopback PostGIS and
Redis. Validate fresh Alembic upgrade, full backend suite, API-client/MCP tests,
web lint/typecheck, production build, browser regressions, and production browser
sharing acceptance against the real API/PostGIS. Hosted PR checks must pass
before merging; do not bypass failed or missing checks.

Sharing migration `202609290002` requires coordinated migration/API release;
old API processes cannot create shares after the required expiry column is
added. See `sharing-safety.md`. Merging code does not migrate, deploy, ingest,
configure credentials, or establish live provider coverage. Crawls cover their
bounded configured horizons and surface partial coverage; they do not promise
all provider listings. Provider behavior in new crawler tests is fixture-based.

## Preservation and restoration

Cleanup preserves all original refs in a Git bundle, records all worktree
statuses, and archives source files (including dirty/untracked work) before
removing redundant worktrees. Machine-local archives stay outside the public
Git history. Each retired branch has a local tag under
`archive/2026-09-29/<original-branch-name>`.

To restore a branch: `git branch recovery/<name> archive/2026-09-29/<original-branch-name>`,
then `git worktree add /desired/path recovery/<name>`. Source archives are needed
for ignored local files. The full backup is retained under the primary
checkout's `.git/cleanup-backups/2026-09-29/`; keep it until deferred proposals
and local configurations are deliberately resolved.
