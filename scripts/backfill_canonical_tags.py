#!/usr/bin/env python
"""Rewrite stored event tags into canonical form. Idempotent, no LLM, no cost.

40% of stored tags carry no ``#`` prefix and the largest single tag is stored as
``HighEnergy``, so hyphenation and casing fork one concept into several
non-matching tags. This rewrites *form only* -- ``HighEnergy`` becomes
``#highenergy``, ``#live-music`` becomes ``#livemusic``.

It rewrites form only and deliberately does NOT delete out-of-vocabulary tags,
so a bulk pass over the whole corpus stays reversible in meaning: nothing is
relabelled and nothing is classified away by a script run at scale.

Note that ingestion is stricter. ``DataPipelineService`` filters tags to the
controlled vocabulary whenever it writes, so any event that receives an update
through a normal worker cycle will have its performer names and ticket types
dropped, whether or not this backfill has ever run.

Dry run by default -- the database is shared across worktrees:

    DATABASE_URL=postgresql+psycopg2://... python scripts/backfill_canonical_tags.py
    DATABASE_URL=... python scripts/backfill_canonical_tags.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.models.event import Event
from app.services.tags import canonical_tag


def canonicalize(tags: list[str]) -> list[str]:
    """Canonical form, order preserved, duplicates collapsed."""
    rewritten: list[str] = []
    for tag in tags:
        canonical = canonical_tag(tag)
        if canonical is not None and canonical not in rewritten:
            rewritten.append(canonical)
    return rewritten


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes; without this the script only reports",
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--limit", type=int, default=None, help="cap rows examined")
    args = parser.parse_args()

    if not args.database_url:
        print("Set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2

    engine = create_engine(args.database_url)
    changed = 0
    examined = 0
    samples: list[tuple[list[str], list[str]]] = []

    with Session(engine) as session:
        statement = select(Event).order_by(Event.id)
        if args.limit is not None:
            statement = statement.limit(args.limit)

        for event in session.exec(statement):
            examined += 1
            current = [t for t in (event.tags or []) if isinstance(t, str)]
            rewritten = canonicalize(current)
            if rewritten == current:
                continue

            changed += 1
            if len(samples) < 10:
                samples.append((current, rewritten))
            if args.apply:
                event.tags = rewritten
                session.add(event)

        if args.apply:
            session.commit()

    for before, after in samples:
        print(f"  {before}\n    -> {after}")

    verb = "Rewrote" if args.apply else "Would rewrite"
    print(f"\n{verb} {changed} of {examined} events.")
    if not args.apply and changed:
        print("Dry run -- re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
