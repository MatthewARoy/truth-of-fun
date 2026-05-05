from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.core.database import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check(session: Session = Depends(get_session)) -> dict[str, str]:
    session.exec(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/sources")
def source_health() -> dict[str, Any]:
    """Per-source health status showing last run, event counts, and tier.

    Returns the union of (a) sources the worker has reported on at least once,
    and (b) all sources registered in the ingestion registry. Sources that
    haven't been run yet appear with status="unknown".
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

    for name, state in _source_health_state.items():
        sources[name] = {
            "name": name,
            "status": state.get("status", "unknown"),
            "last_run_at": state.get("last_run_at"),
            "last_event_count": state.get("last_event_count"),
            "consecutive_zeros": state.get("consecutive_zeros", 0),
        }

    return {"sources": list(sources.values())}
