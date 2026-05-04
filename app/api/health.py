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
    """Per-source health status showing last run and event counts."""
    from app.worker import _source_health_state

    return {"sources": _source_health_state}
