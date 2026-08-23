#!/usr/bin/env python
"""Report how many live events each weighted vibe tag actually matches.

The concierge ranks on ``_INTENT_VIBE_PROFILES``, but a weighted tag that
matches nothing contributes nothing -- and nothing in CI can catch that, because
the test suite has no corpus. Run this against a populated database.

    DATABASE_URL=postgresql+psycopg2://... python scripts/audit_vibe_coverage.py

Exits non-zero if any weighted tag falls below --min-events, so it can gate a
deploy or run from cron.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text

from app.services.concierge import _INTENT_VIBE_PROFILES
from app.services.tags import resolve_vibe_tag

# Canonicalize stored tags in SQL so mixed-form rows (``HighEnergy``,
# ``#live-music``) count towards the tag they mean.
_COUNT_SQL = text(
    """
    SELECT regexp_replace(lower(ltrim(tag, '#')), '[^a-z0-9+]', '', 'g') AS canonical,
           count(DISTINCT id) AS events
    FROM events, jsonb_array_elements_text(tags) AS tag
    GROUP BY canonical
    """
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-events",
        type=int,
        default=20,
        help="fail if a weighted tag matches fewer events than this",
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        print("Set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2

    engine = create_engine(args.database_url)
    with engine.connect() as conn:
        # The SQL canonicalizes form; fold aliases in Python so the report
        # reflects what the recommender actually matches.
        counts: dict[str, int] = {}
        for row in conn.execute(_COUNT_SQL):
            resolved = resolve_vibe_tag(row.canonical)
            if resolved is None:
                continue
            counts[resolved] = counts.get(resolved, 0) + row.events
        total = conn.execute(text("SELECT count(*) FROM events")).scalar_one()

    print(f"{total} events in corpus\n")
    starved: list[str] = []

    for intent in sorted(_INTENT_VIBE_PROFILES):
        print(intent)
        for tag, weight in sorted(
            _INTENT_VIBE_PROFILES[intent].items(), key=lambda kv: -kv[1]
        ):
            canonical = resolve_vibe_tag(tag) or tag
            matched = counts.get(canonical, 0)
            flag = "" if matched >= args.min_events else "  <-- STARVED"
            print(f"  {canonical:<16} weight {weight:>4.1f}  {matched:>5} events{flag}")
            if matched < args.min_events:
                starved.append(f"{intent}:{canonical} ({matched})")
        print()

    if starved:
        print(f"{len(starved)} weighted tag(s) below {args.min_events} events:")
        for entry in starved:
            print(f"  {entry}")
        return 1

    print("All weighted tags have adequate coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
