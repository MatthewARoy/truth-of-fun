import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, text
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.event import Event
from app.models.source_health import SourceHealthRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

#: A source that hasn't completed a run in this long is stale regardless of the
#: status it last reported — the worker itself may be down. Two full ingestion
#: cycles (6h each) plus headroom.
STALE_SOURCE_AFTER = timedelta(hours=14)


@router.get("", operation_id="getHealth", summary="Database-backed health check")
def health_check(session: Session = Depends(get_session)) -> dict[str, str]:
    """Report API and database reachability. Used by the compose healthcheck."""
    session.exec(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/live", operation_id="getLiveness", summary="Process liveness probe")
def liveness() -> dict[str, str]:
    """Report that the process is up, without touching the database.

    Separate from ``/health`` so an orchestrator does not restart a healthy API
    process just because Postgres is briefly unreachable — that is a readiness
    problem, not a liveness one.
    """
    return {"status": "ok"}


@router.get("/ready", operation_id="getReadiness", summary="Readiness probe")
def readiness(response: Response, session: Session = Depends(get_session)) -> dict[str, str]:
    """Report whether the API can serve traffic, i.e. whether the DB answers.

    Returns 503 (not an exception) when the database is unreachable so load
    balancers see a clean signal and the reason is in the body.
    """
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Readiness check failed: database unreachable.")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": f"{type(exc).__name__}: {exc}"[:200]}
    return {"status": "ready", "database": "connected"}


@router.get("/sources", operation_id="getSourceHealth", summary="Per-source ingestion health")
def source_health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Per-source health status showing last run, event counts, and tier.

    Returns the union of (a) sources the worker has persisted health for,
    (b) in-process state when the worker runs embedded, and (c) all sources
    registered in the ingestion registry. Sources that haven't been run yet
    appear with status="unknown".
    """
    return {"sources": _collect_source_health(session)}


@router.get(
    "/summary",
    operation_id="getHealthSummary",
    summary="Single-call operational status: is anything broken right now?",
)
def health_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Aggregate every health signal into one verdict plus a list of problems.

    This is the endpoint to poll (or curl) when the question is "is the
    platform OK?". It answers with:

    ``status``
        ``ok`` — nothing wrong; ``degraded`` — something is wrong but the API
        still serves; ``failing`` — sources are broken or the database is down.
    ``problems``
        A list of human-readable strings, each naming the subsystem. Empty when
        ``status`` is ``ok``. These are the lines worth alerting on.

    Every number below is read from the database, never inferred: an empty
    corpus reports zero, not an estimate.
    """
    problems: list[str] = []
    checked_at = datetime.now(timezone.utc)

    database_ok = True
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:
        database_ok = False
        problems.append(f"database: unreachable ({type(exc).__name__}: {exc})"[:300])
        logger.exception("Health summary: database unreachable.")

    sources = _collect_source_health(session) if database_ok else []
    by_status: dict[str, int] = {}
    for source in sources:
        by_status[source["status"]] = by_status.get(source["status"], 0) + 1

    ran_sources = [s for s in sources if s.get("last_run_at")]
    stale_sources = [s for s in sources if s.get("is_stale")]

    # Every source going stale at once means the worker stopped, not that
    # eleven scrapers broke independently. Report the actual diagnosis once
    # instead of one indistinguishable line per source.
    worker_is_down = bool(ran_sources) and len(stale_sources) == len(ran_sources)
    if worker_is_down:
        newest_run = max(str(s["last_run_at"]) for s in ran_sources)
        problems.append(
            f"worker: no source has completed a run since {newest_run} — "
            "the ingestion worker looks stopped (`make worker-loop`, or "
            "`docker compose up -d worker`)"
        )

    for source in sources:
        if source["status"] == "failing":
            detail = source.get("last_error") or "returned 0 events on consecutive runs"
            problems.append(f"source {source['name']}: failing — {detail}"[:300])
        elif source["status"] == "degraded":
            problems.append(f"source {source['name']}: degraded — returned 0 events last run")
        if source.get("is_stale") and not worker_is_down:
            problems.append(
                f"source {source['name']}: stale — no completed run since "
                f"{source.get('last_run_at') or 'never'}"
            )

    events = _event_corpus_stats(session) if database_ok else {}
    if database_ok and events.get("upcoming_events", 0) == 0:
        problems.append(
            "corpus: no upcoming events — the feed would render empty "
            "(run `make seed` for demo data or `make worker` to ingest)"
        )

    if not database_ok or by_status.get("failing"):
        overall = "failing"
    elif problems:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "checked_at": checked_at.isoformat(),
        "problems": problems,
        "database": {"connected": database_ok},
        "sources": {
            "total": len(sources),
            "by_status": by_status,
            "stale": len(stale_sources),
            "worker_stalled": worker_is_down,
        },
        "events": events,
    }


def _collect_source_health(session: Session) -> list[dict[str, Any]]:
    """Union of registry-known, DB-persisted, and in-process source health."""
    from app.ingestion import registry
    from app.worker import _source_health_state

    sources: dict[str, dict[str, Any]] = {}

    try:
        registered = registry.list_sources()
    except Exception:
        logger.exception("Could not list registered ingestion sources.")
        registered = []

    for name in registered:
        sources[name] = {
            "name": name,
            "status": "unknown",
            "last_run_at": None,
            "last_event_count": None,
            "consecutive_zeros": 0,
            "last_error": None,
            "last_error_at": None,
            "last_success_at": None,
        }

    # Health persisted by the worker process (the normal deployment shape).
    try:
        records = session.exec(select(SourceHealthRecord)).all()
    except Exception:
        logger.exception("Could not read persisted source health.")
        records = []
    for record in records:
        sources[record.source_name] = {
            "name": record.source_name,
            "status": record.status,
            "last_run_at": _iso(record.last_run_at),
            "last_event_count": record.last_event_count,
            "consecutive_zeros": record.consecutive_zeros,
            "last_error": record.last_error,
            "last_error_at": _iso(record.last_error_at),
            "last_success_at": _iso(record.last_success_at),
        }

    # In-process state (worker embedded in this process) wins only when fresher.
    for name, state in _source_health_state.items():
        existing_run_at = sources.get(name, {}).get("last_run_at")
        in_process_run_at = state.get("last_run_at")
        if existing_run_at and in_process_run_at and in_process_run_at <= existing_run_at:
            continue
        sources[name] = {
            "name": name,
            "status": state.get("status", "unknown"),
            "last_run_at": in_process_run_at,
            "last_event_count": state.get("last_event_count"),
            "consecutive_zeros": state.get("consecutive_zeros", 0),
            "last_error": state.get("last_error"),
            "last_error_at": state.get("last_error_at"),
            "last_success_at": state.get("last_success_at"),
        }

    cutoff = datetime.now(timezone.utc) - STALE_SOURCE_AFTER
    for source in sources.values():
        source["is_stale"] = _is_before(source.get("last_run_at"), cutoff)

    return list(sources.values())


def _event_corpus_stats(session: Session) -> dict[str, Any]:
    """Corpus freshness: an empty or stale feed is an outage users can see."""
    try:
        total = session.exec(select(func.count()).select_from(Event)).one()
        upcoming = session.exec(
            select(func.count())
            .select_from(Event)
            .where(Event.start_at >= func.now(), Event.status == "scheduled")
        ).one()
        newest_ingest = session.exec(select(func.max(Event.created_at))).one()
    except Exception:
        logger.exception("Could not compute event corpus stats.")
        return {}

    return {
        "total_events": _scalar(total),
        "upcoming_events": _scalar(upcoming),
        "newest_event_first_seen_at": _iso(_scalar(newest_ingest)),
    }


def _scalar(value: Any) -> Any:
    """session.exec() returns a Row for aggregate selects on some drivers."""
    if isinstance(value, tuple):
        return value[0] if value else None
    return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _is_before(iso_value: Any, cutoff: datetime) -> bool:
    if not isinstance(iso_value, str):
        # Never run is reported via status="unknown", not as staleness.
        return False
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < cutoff
