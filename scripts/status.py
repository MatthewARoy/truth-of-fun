#!/usr/bin/env python
"""Print a readable operational status for a running Truth of Fun API.

Wraps ``GET /health/summary`` so the answer to "is anything broken?" is one
command rather than a curl plus mental JSON parsing. Exit codes make it usable
as a deploy smoke test or a cron check:

    0  ok        — nothing wrong
    1  degraded  — serving, but something needs attention
    2  failing   — sources broken or the database is down
    3  unreachable — the API itself did not answer

Usage:
    make status                        # defaults to http://127.0.0.1:8000
    python scripts/status.py --api-url https://api.example.com
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_FAILING = 2
EXIT_UNREACHABLE = 3

_EXIT_BY_STATUS = {"ok": EXIT_OK, "degraded": EXIT_DEGRADED, "failing": EXIT_FAILING}

# Only emit colour to a real terminal, so piping into a file or a cron mail
# body stays clean.
_USE_COLOR = sys.stdout.isatty()
_COLORS = {"ok": "\033[32m", "degraded": "\033[33m", "failing": "\033[31m"}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _paint(text: str, color: str) -> str:
    if not _USE_COLOR or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def _dim(text: str) -> str:
    return f"{_DIM}{text}{_RESET}" if _USE_COLOR else text


def fetch_summary(api_url: str, *, timeout: float) -> dict[str, Any]:
    url = f"{api_url.rstrip('/')}/health/summary"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def render(summary: dict[str, Any]) -> str:
    status = str(summary.get("status", "unknown"))
    lines = [f"Truth of Fun: {_paint(status.upper(), status)}"]

    database = summary.get("database", {})
    lines.append(f"  database   {'connected' if database.get('connected') else 'UNREACHABLE'}")

    sources = summary.get("sources", {})
    by_status = sources.get("by_status", {})
    if by_status:
        breakdown = ", ".join(f"{count} {name}" for name, count in sorted(by_status.items()))
        lines.append(f"  sources    {sources.get('total', 0)} total ({breakdown})")

    events = summary.get("events", {})
    if events:
        lines.append(
            f"  events     {events.get('upcoming_events', 0)} upcoming "
            f"of {events.get('total_events', 0)} total"
        )
        newest = events.get("newest_event_first_seen_at")
        if newest:
            lines.append(_dim(f"             newest first seen {newest}"))

    problems = summary.get("problems") or []
    if problems:
        lines.append("")
        lines.append(f"  {len(problems)} problem(s):")
        lines.extend(f"    - {problem}" for problem in problems)
    else:
        lines.append("")
        lines.append("  No problems detected.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the API (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Request timeout in seconds"
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead")
    args = parser.parse_args()

    try:
        summary = fetch_summary(args.api_url, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"API returned HTTP {exc.code} for {args.api_url}/health/summary", file=sys.stderr)
        return EXIT_UNREACHABLE
    except Exception as exc:
        print(
            f"Could not reach the API at {args.api_url}: {type(exc).__name__}: {exc}\n"
            "Is it running? Try `make api` locally or `docker compose up -d api`.",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    print(json.dumps(summary, indent=2) if args.json else render(summary))
    return _EXIT_BY_STATUS.get(str(summary.get("status")), EXIT_FAILING)


if __name__ == "__main__":
    raise SystemExit(main())
