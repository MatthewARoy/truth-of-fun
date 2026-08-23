"""Geocode events already stored on a city-centroid guess.

The ingestion hook only reaches events a source re-emits. An event whose
listing has already rolled off its feed keeps whatever coordinate it was
written with — a city centroid at ``location_confidence`` 0.4 — and stays
invisible to every radius query for the rest of its life. This script is
what moves those rows.

It shares the geocoder, the persistent cache and the write rule with the
ingestion path, so a name resolved here is not re-resolved during the next
cycle, and a name that fails here is not retried until its cache entry
expires.

Usage:
    python -m scripts.backfill_geocode                  # report only
    python -m scripts.backfill_geocode --apply          # write changes
    python -m scripts.backfill_geocode --limit 50       # cap the lookups
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import Session

from app.core.database import engine
from app.services.geocoding import (
    MIN_SEARCHABLE_LOCATION_CONFIDENCE,
    GeocodeResult,
    VenueGeocoder,
    build_geocoder,
    worth_writing,
)


@dataclass(frozen=True)
class GeocodeCandidate:
    """An event whose stored coordinate is a fallback, not a location."""

    event_id: int
    title: str
    venue_name: str | None
    raw_address: str | None
    location_confidence: float


@dataclass(frozen=True)
class PlannedChange:
    candidate: GeocodeCandidate
    result: GeocodeResult

    @property
    def event_id(self) -> int:
        return self.candidate.event_id


def find_candidates(session: Session, *, limit: int | None = None) -> list[GeocodeCandidate]:
    """Rows below the radius-search threshold, worst first.

    Ordered so that a bounded run spends its lookups on the events carrying
    the least information — an event with neither a resolved venue nor a
    city has nothing else going for it.
    """
    sql = (
        "SELECT id, title, venue_name, raw_address, location_confidence"
        " FROM events"
        " WHERE location_confidence < :threshold"
        "   AND (raw_address IS NOT NULL OR venue_name IS NOT NULL)"
        " ORDER BY location_confidence ASC, start_at DESC"
    )
    if limit is not None:
        sql += " LIMIT :limit"

    params: dict[str, object] = {"threshold": MIN_SEARCHABLE_LOCATION_CONFIDENCE}
    if limit is not None:
        params["limit"] = limit

    return [
        GeocodeCandidate(
            event_id=row.id,
            title=row.title,
            venue_name=row.venue_name,
            raw_address=row.raw_address,
            location_confidence=float(row.location_confidence or 0.0),
        )
        for row in session.execute(text(sql), params).all()
    ]


async def plan_backfill(
    *,
    session: Session | None,
    geocoder: VenueGeocoder,
    candidates: list[GeocodeCandidate],
) -> list[PlannedChange]:
    """Resolve each candidate and keep the answers worth writing."""
    geocoder.reset_run_budget()

    changes: list[PlannedChange] = []
    for candidate in candidates:
        if candidate.location_confidence >= MIN_SEARCHABLE_LOCATION_CONFIDENCE:
            continue

        result = await geocoder.resolve(
            session=session,
            venue_name=candidate.venue_name,
            raw_address=candidate.raw_address,
            city=None,
        )
        if worth_writing(result, candidate.location_confidence):
            assert result is not None  # narrowed by worth_writing
            changes.append(PlannedChange(candidate=candidate, result=result))

    return changes


def apply_changes(session: Session, changes: list[PlannedChange]) -> None:
    for change in changes:
        session.execute(
            text(
                # events.location is a geometry column (see app/models/event.py);
                # casting to geography here is a runtime DatatypeMismatch.
                "UPDATE events"
                " SET location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),"
                "     location_confidence = :confidence"
                " WHERE id = :event_id"
            ),
            {
                "lon": change.result.lon,
                "lat": change.result.lat,
                "confidence": change.result.confidence,
                "event_id": change.event_id,
            },
        )


async def _run(*, limit: int | None, apply: bool) -> None:
    geocoder = build_geocoder()
    if geocoder.provider is None:
        print(
            "No geocoding provider configured — set GEOCODING_PROVIDER=nominatim "
            "to resolve venues missing from the static table."
        )

    with Session(engine) as session:
        candidates = find_candidates(session, limit=limit)
        print(f"{len(candidates)} event(s) below the radius-search threshold")

        changes = await plan_backfill(
            session=session, geocoder=geocoder, candidates=candidates
        )
        # The cache is worth keeping even on a dry run: the lookups were
        # already spent, and a second run should not re-spend them.
        session.commit()

        print(f"{len(changes)} resolved to a searchable coordinate")
        for change in changes[:20]:
            print(
                f"  #{change.event_id} {change.candidate.title[:44]!r}"
                f" @ {change.candidate.venue_name!r}"
                f" -> ({change.result.lat:.5f}, {change.result.lon:.5f})"
                f" {change.result.precision} {change.result.confidence}"
            )
        if len(changes) > 20:
            print(f"  ... and {len(changes) - 20} more")

        if not apply:
            print("\ndry run — pass --apply to write these coordinates")
            return

        apply_changes(session, changes)
        session.commit()
        print(f"\nupdated {len(changes)} event(s)")

    provider = geocoder.provider
    if provider is not None and hasattr(provider, "close"):
        await provider.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the resolved coordinates (default is a dry-run report)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only consider this many events (lookups are rate-limited to 1/s)",
    )
    args = parser.parse_args()
    asyncio.run(_run(limit=args.limit, apply=args.apply))


if __name__ == "__main__":
    main()
