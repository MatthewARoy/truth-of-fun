# Vibe tag canonicalization and controlled vocabulary

Date: 2026-08-23

## Problem

The concierge's `date_night` intent ranks events with a vibe signal that resolves
to ~0 for essentially every candidate. Vibe match is 50% of the recommender score
(`RecommenderService.VIBE_WEIGHT`), so the dominant ranking signal is dead.

Measured against the live events table on 2026-08-23 (2089 events, 1565 with
non-empty tags, 1440 distinct tags):

| profile tag | events matched | after canonicalization |
| --- | --- | --- |
| `#date` | 0 | 0 |
| `#chill` | 0 | 0 |
| `#jazz` | 0 | 0 |
| `#film` | 0 | 0 |
| `#art` | 0 | 0 |
| `#livemusic` | 42 | 82 |

Five of the six weighted `date_night` tags match nothing; the only one that
matches carries the lowest weight (1.0).

### Root causes

1. **Divergent normalizers.** Four independent implementations disagree:
   - `recommender.normalize_key` strips a leading `#`, lowercases.
   - `discovery._score_event_for_user` lowercases but does *not* touch `#`.
   - `user_profile._normalize_tags` adds `#` and strips whitespace.
   - `vibe_tagger._normalize_tags` does a fourth variation.
   None collapse `-`/`_`, so `#live-music` (40 events) and `#livemusic` (42) are
   distinct, non-matching tags.

2. **Mixed storage form.** 1956 of 4828 stored tags (40%) have no `#` prefix.
   The single largest tag, `HighEnergy` (586 events), is stored bare and
   CamelCase.

3. **Non-vibe metadata in `tags`.** `ticketmaster._extract_tags` writes performer
   names verbatim (`Alex Ramon`, `San Francisco Giants`,
   `Laugh Factory @ Silver Legacy`). Ticket-type and operational strings
   (`#GeneralAdmission`, `#drink-minimum`, `#strict-entry-policy`, `#refund`,
   `#disappointed`) also land in `tags`.

4. **Unconstrained tagger.** `ClaudeVibeTagger` prompts for free-form tags, so the
   vocabulary explodes: 1440 distinct tags over 1565 tagged events, nearly 1:1.
   Tags that appear once carry no ranking signal.

### What normalization cannot fix

Canonicalization raises `#livemusic` from 42 to 82 and unifies `HighEnergy`, but
`#date`, `#chill`, `#jazz`, `#film`, `#art` remain at 0 — the corpus contains no
date vocabulary. The closest existing tags are `intimate` (5 events), `relaxed`
(5), `musicaltheatre` (8), `cocktaillounge` (4). `date_night` cannot be made to
work by matching alone; it needs the corpus re-tagged.

## Design

### 1. `app/services/tags.py` — single canonicalizer

- `canonical_tag(tag) -> str | None`: strip, lowercase, drop leading `#`, remove
  `-`/`_`/whitespace, re-prefix `#`. Returns `None` for empty input.
- `VIBE_VOCABULARY: frozenset[str]`: closed set containing every tag named in
  `_INTENT_VIBE_PROFILES`.
- `canonical_vibe_tags(tags) -> list[str]`: canonicalize, filter to vocabulary,
  de-duplicate, preserve order.

### 2. Collapse the four normalizers

`recommender.normalize_key`, `user_profile._normalize_tags` and
`vibe_tagger._normalize_tags` all delegate to `canonical_tag`.
`discovery._score_event_for_user` has no call sites and is deleted.

This layer fixes ranking on existing data: the recommender canonicalizes event
tags at read time, so no backfill is required for the ranking repair.

### 3. Write-side cleanup

- `ticketmaster._extract_tags` stops writing performer names into `tags`.
- `nineteen_hz` `["HighEnergy"]` and `meetup` `["Social"]` become canonical.
- `data_pipeline` applies `canonical_vibe_tags()` at write, so out-of-vocabulary
  noise never lands.

### 4. Constrained tagger

`ClaudeVibeTagger` receives the vocabulary in its prompt and must choose from it.
Out-of-vocabulary output is dropped rather than stored.

### 5. Query filter

`discovery.py` `Event.tags.contains([vibe_tag])` was worse than reported. The
`tags` column is declared as generic SQLAlchemy `JSON`, which has no containment
operator, so the expression compiled to `events.tags LIKE '%' || ... ::JSON`
and Postgres rejected it:

    psycopg2.errors.UndefinedFunction: operator does not exist: jsonb ~~ text

`GET /events?vibe_tag=...` therefore returned **HTTP 500**, not an empty list.
No test covered it. Replaced with a canonicalizing `EXISTS` subquery, verified
against the live database: `#highenergy`, `HighEnergy` and `high-energy` all
return 606 events where the old expression raised.

### 5a. Synonym layer

Filtering writes to a closed vocabulary destroys near-misses -- `#Outdoor`
(singular) and `#standup` are real vibes that would simply vanish. A small
`_SYNONYMS` map folds unambiguous aliases onto their vocabulary entry:
`#standup`/`#comedyclub` to `#comedy` (159 events), `#relaxed` to `#chill`,
`#datenight` to `#date`, `#outdoor` to `#outdoors`.

Only morphological variants and exact aliases qualify. Genuinely broader terms
are excluded on purpose: `#liveentertainment` (114 events) is *not* mapped to
`#livemusic`, because a circus is live entertainment and not live music.

This is kept separate from `canonical_tag` as `resolve_vibe_tag`, because the
step is semantic and the backfill must restyle tags without relabelling events.

### 6. Scripts (written, not run)

- `scripts/backfill_canonical_tags.py`: form-only, idempotent, no LLM, no cost.
  Rewrites tag *form* only; does not delete junk tags.
- `scripts/audit_vibe_coverage.py`: reports live match counts per profile tag.

Both are left unrun. The shared database is visible to other worktrees, and
LLM re-tagging spends real API budget — those are the maintainer's calls.

### 7. Testing

Deterministic, runnable by the existing suite with no live corpus:

- every tag in `_INTENT_VIBE_PROFILES` is in `VIBE_VOCABULARY`;
- every vocabulary tag is a fixed point of `canonical_tag`;
- `LiveMusic`, `live-music`, `#live_music`, `#livemusic` collapse to one key;
- an event tagged `HighEnergy` scores > 0 for `general_night_out`;
- `data_pipeline` drops performer names and out-of-vocabulary noise.

A live-corpus coverage assertion is deliberately *not* a CI test: the suite has
no populated database, so such a test would silently skip — which is how this
regressed unnoticed. Live coverage is `scripts/audit_vibe_coverage.py` instead.

## Measured effect

Events receiving a non-zero vibe score, live corpus of 2089 events:

| intent | before | after |
| --- | --- | --- |
| `date_night` | 42 | 96 |
| `out_of_town_guests` | 50 | 96 |
| `general_night_out` | 767 | 879 |
| `bar_crawl` | 717 | 731 |

Tag coverage: `#comedy` 107 to 266, `#livemusic` 42 to 92, and `date_night`'s
five dead tags are no longer all zero -- but at 1-6 events each they remain
starved. `date_night` mean vibe score rises from 0.20 to 0.56 out of 100.

## Known limitations

- `date_night` remains weak until the corpus is re-tagged. Normalization cannot
  invent `#jazz` events that do not exist.
- Only 601 of 2089 events have a description long enough to re-tag from.
- With vocabulary filtering active and no `ANTHROPIC_API_KEY` present, newly
  ingested events carry only their source-provided tags until a re-tag runs.
- `#highenergy` covers 606 of 2089 events (~29%), so it barely discriminates.
  Profile-weight quality is out of scope here.
