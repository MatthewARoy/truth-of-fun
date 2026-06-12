from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.source_health import SourceHealthRecord

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check(session: Session = Depends(get_session)) -> dict[str, str]:
    session.exec(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/sources")
def source_health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Per-source health status showing last run, event counts, and tier.

    Returns the union of (a) sources the worker has persisted health for,
    (b) in-process state when the worker runs embedded, and (c) all sources
    registered in the ingestion registry. Sources that haven't been run yet
    appear with status="unknown".
    """
    from app.ingestion import registry
    from app.worker import _source_health_state

    sources: dict[str, dict[str, Any]] = {}

    try:
        registered = registry.list_sources()
    except Exception:
        registered = []

    for name in registered:
        sources[name] = {
            "name": name,
            "status": "unknown",
            "last_run_at": None,
            "last_event_count": None,
            "consecutive_zeros": 0,
        }

    # Health persisted by the worker process (the normal deployment shape).
    try:
        records = session.exec(select(SourceHealthRecord)).all()
    except Exception:
        records = []
    for record in records:
        sources[record.source_name] = {
            "name": record.source_name,
            "status": record.status,
            "last_run_at": record.last_run_at.isoformat() if record.last_run_at else None,
            "last_event_count": record.last_event_count,
            "consecutive_zeros": record.consecutive_zeros,
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
        }

    return {"sources": list(sources.values())}
