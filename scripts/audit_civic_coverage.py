#!/usr/bin/env python
"""Check reviewed civic occurrence expectations using only public catalog reads.

Run with DATABASE_URL and --manifest. No crawling, provider calls, database
writes or scheduling. Exit 1 means a dated expectation is missing with fresh
corpus evidence; exit 3 means evidence is insufficient; exit 2 is input/read
failure. A report with only covered/inactive dates exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from pydantic import ValidationError

from app.services.civic_coverage import CoverageManifest, SF, evaluate_occurrence


def read_public_snapshot(connection, *, now: datetime, horizon_days: int) -> tuple[list[dict], dict]:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout = '10s'"))
    start = datetime.combine(now.astimezone(SF).date(), datetime.min.time(), tzinfo=SF)
    end = start + timedelta(days=horizon_days + 1)
    events = [dict(row) for row in connection.execute(text("""
        SELECT id, title, venue_name, source_name, start_at, status
        FROM events WHERE start_at >= :start AND start_at < :end
        ORDER BY start_at, id LIMIT 10001
    """), {"start": start, "end": end}).mappings()]
    if len(events) > 10000:
        raise ValueError("coverage read exceeds 10000 rows; narrow the horizon")
    health = {row["source_name"]: dict(row) for row in connection.execute(text("""
        SELECT source_name, status, last_run_at, last_success_at, last_error
        FROM source_health
    """)).mappings()}
    return events, health


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--horizon-days", type=int, default=180, choices=range(1, 366))
    args = parser.parse_args(argv)
    try:
        if args.manifest.stat().st_size > 256_000:
            raise ValueError("manifest is too large")
        manifest = CoverageManifest.model_validate_json(args.manifest.read_text())
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("Set DATABASE_URL")
    except ValidationError as error:
        fields = [".".join(map(str, item["loc"])) for item in error.errors(include_input=False)]
        print("Invalid coverage manifest fields: " + ", ".join(fields), file=sys.stderr)
        return 2
    except (ValueError, OSError) as error:
        # Validation details are local manifest data, never connection secrets.
        print(f"Invalid coverage input ({type(error).__name__})", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    engine = None
    try:
        engine = create_engine(database_url, connect_args={"connect_timeout": 5})
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required for enforced read-only transactions")
        with engine.connect() as connection:
            with connection.begin():
                events, health = read_public_snapshot(connection, now=now, horizon_days=args.horizon_days)
        report = [evaluate_occurrence(item, events=events, health=health, now=now,
                  horizon_days=args.horizon_days, source_horizon_days=manifest.source_horizon_days) for item in manifest.expectations]
        print(json.dumps({"checked_at": now.isoformat(), "horizon_days": args.horizon_days,
                          "results": report}, indent=2))
    except Exception as error:
        print(f"Coverage database read failed ({type(error).__name__}); verify connection and schema", file=sys.stderr)
        return 2
    finally:
        if engine:
            engine.dispose()
    if any(item["status"] == "missing_current_corpus" for item in report):
        return 1
    if any(item["status"] in {"corpus_stale", "expectation_stale", "schedule_unverified", "coverage_horizon_unverified"} for item in report):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
