from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import func, update
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import create_db_and_tables, engine
from app.ingestion import registry
from app.models.event import Event
from app.models.source_health import SourceHealthRecord
from app.services.alerting import send_alert
from app.services.data_pipeline import DataPipelineService
from app.services.secrets_store import get_secrets_store

logger = logging.getLogger(__name__)

# Module-level source health state, readable by the /health/sources endpoint.
_source_health_state: dict[str, dict[str, Any]] = {}


class DataPipelineLike(Protocol):
    async def process_raw_events(
        self,
        *,
        session: Session,
        raw_events: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Process raw event payloads and write canonical records."""


class SourceLike(Protocol):
    source_name: str

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch raw event payloads."""

    async def close(self) -> None:
        """Release source resources."""


@dataclass
class WorkerRunResult:
    started_at: datetime
    finished_at: datetime
    total_events_fetched: int
    per_source_counts: dict[str, int]
    pipeline_summary: dict[str, int]


class IngestionWorker:
    """Async worker that executes ingestion and pipeline processing on a schedule."""

    def __init__(
        self,
        *,
        run_interval_seconds: int = 6 * 60 * 60,
        pipeline_service: DataPipelineLike | None = None,
        session_factory: Callable[[], Session] | None = None,
        source_registry: Any = None,
        canary_history_size: int = 5,
        quota_window_hours: int | None = None,
    ) -> None:
        self._run_interval_seconds = run_interval_seconds
        self._pipeline_service = pipeline_service or DataPipelineService()
        self._session_factory = session_factory or (lambda: Session(engine))
        self._registry = source_registry or registry
        self._source_count_history: dict[str, deque[int]] = defaultdict(
            lambda: deque(maxlen=canary_history_size)
        )
        self._pending_alerts: list[tuple[str, str, str]] = []
        self._quota_window_hours = (
            quota_window_hours
            if quota_window_hours is not None
            else get_settings().aaim_quota_window_hours
        )

    async def run_forever(self) -> None:
        logger.info(
            "Starting ingestion worker loop (interval=%ss).",
            self._run_interval_seconds,
        )
        while True:
            await self.run_once()
            await asyncio.sleep(self._run_interval_seconds)

    async def run_once(self) -> WorkerRunResult:
        started_at = datetime.now(timezone.utc)
        all_events: list[dict[str, Any]] = []
        per_source_counts: dict[str, int] = {}

        # Roll over quota windows before fetching so a key whose daily cap has
        # reset is available again for this run.
        self._reset_quota_exhausted_keys()

        for source_name in self._registry.list_sources():
            source: SourceLike | None = None
            fetched_events: list[dict[str, Any]] = []
            try:
                source = self._registry.create(source_name)
                fetched_events = await source.fetch_events()
            except Exception:
                logger.exception("Source '%s' failed during fetch.", source_name)
            finally:
                if source is not None:
                    with suppress(Exception):
                        await source.close()

            per_source_counts[source_name] = len(fetched_events)
            all_events.extend(fetched_events)
            self._log_canary_metrics(source_name=source_name, current_count=len(fetched_events))
            self._log_quota_health(source_name=source_name)

        with self._session_factory() as session:
            pipeline_summary = await self._pipeline_service.process_raw_events(
                session=session,
                raw_events=all_events,
            )

        self._mark_past_events()
        self._persist_source_health()

        # Flush pending alerts (never blocks the pipeline)
        for title, message, severity in self._pending_alerts:
            with suppress(Exception):
                await send_alert(title=title, message=message, severity=severity)
        self._pending_alerts.clear()

        finished_at = datetime.now(timezone.utc)
        result = WorkerRunResult(
            started_at=started_at,
            finished_at=finished_at,
            total_events_fetched=len(all_events),
            per_source_counts=per_source_counts,
            pipeline_summary=pipeline_summary,
        )
        logger.info(
            "Worker run complete: fetched=%s by_source=%s pipeline=%s duration_ms=%s",
            result.total_events_fetched,
            result.per_source_counts,
            result.pipeline_summary,
            int((finished_at - started_at).total_seconds() * 1000),
        )
        return result

    def _mark_past_events(self) -> None:
        """Transition scheduled events to 'past' when they ended more than 24 hours ago."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            with self._session_factory() as session:
                result = session.execute(
                    update(Event)
                    .where(
                        func.coalesce(Event.end_at, Event.start_at) < cutoff,
                        Event.status == "scheduled",
                    )
                    .values(status="past")
                )
                count = result.rowcount
                session.commit()
            if count:
                logger.info("Lifecycle cleanup: marked %s event(s) as past.", count)
        except Exception:
            logger.debug("Lifecycle cleanup skipped (no database session).")

    def _persist_source_health(self) -> None:
        """Write per-source health to the database so the API process can serve it."""
        try:
            with self._session_factory() as session:
                for source_name, state in _source_health_state.items():
                    last_run_at = state.get("last_run_at")
                    record = SourceHealthRecord(
                        source_name=source_name,
                        status=state.get("status", "unknown"),
                        last_event_count=state.get("last_event_count", 0),
                        consecutive_zeros=state.get("consecutive_zeros", 0),
                        last_run_at=(
                            datetime.fromisoformat(last_run_at)
                            if isinstance(last_run_at, str)
                            else None
                        ),
                    )
                    session.merge(record)
                session.commit()
        except Exception:
            logger.debug("Source health persistence skipped (no database session).")

    def _log_canary_metrics(self, *, source_name: str, current_count: int) -> None:
        history = self._source_count_history[source_name]
        historic_avg = (sum(history) / len(history)) if history else 0.0

        logger.info(
            "Canary metric source=%s events_fetched=%s historic_avg=%.2f",
            source_name,
            current_count,
            historic_avg,
        )

        if history and historic_avg > 10 and current_count == 0:
            logger.critical(
                "CANARY ALERT source=%s returned 0 events but historic average is %.2f (>10).",
                source_name,
                historic_avg,
            )
            self._pending_alerts.append((
                f"Source {source_name} returned 0 events",
                f"Historic average was {historic_avg:.1f}. Possible outage or API issue.",
                "critical",
            ))

        history.append(current_count)

        # Update module-level source health state
        prev = _source_health_state.get(source_name, {})
        consecutive_zeros = prev.get("consecutive_zeros", 0)
        if current_count == 0:
            consecutive_zeros += 1
        else:
            consecutive_zeros = 0

        if consecutive_zeros == 0:
            status = "healthy"
        elif consecutive_zeros == 1:
            status = "degraded"
        else:
            status = "failing"

        _source_health_state[source_name] = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_event_count": current_count,
            "status": status,
            "consecutive_zeros": consecutive_zeros,
        }

    def _reset_quota_exhausted_keys(self) -> None:
        """Auto-reactivate AAIM keys whose quota window has rolled over.

        Replaces the manual redis-cli recovery: exhausted keys come back on
        their own once ``aaim_quota_window_hours`` have passed.
        """
        if self._quota_window_hours <= 0:
            return
        window_seconds = self._quota_window_hours * 3600
        try:
            reset_ids = get_secrets_store().reset_exhausted_keys(
                "ticketmaster", window_seconds=window_seconds
            )
        except Exception:
            logger.debug("AAIM quota-window reset skipped.")
            return
        if reset_ids:
            logger.info(
                "AAIM quota-window reset: reactivated %s ticketmaster key(s): %s",
                len(reset_ids),
                ", ".join(reset_ids),
            )

    def _log_quota_health(self, *, source_name: str) -> None:
        if source_name != "ticketmaster":
            return
        try:
            key_health = get_secrets_store().health("ticketmaster")
        except Exception:
            return
        if not key_health:
            logger.warning("AAIM quota health: no ticketmaster keys in secrets store.")
            return

        active_count = sum(1 for item in key_health if item.status == "active")
        exhausted_count = sum(1 for item in key_health if item.status == "exhausted")
        if active_count <= 1:
            logger.warning(
                "AAIM quota health warning: active_ticketmaster_keys=%s exhausted_ticketmaster_keys=%s",
                active_count,
                exhausted_count,
            )
            self._pending_alerts.append((
                "Ticketmaster API key quota low",
                f"Only {active_count} active key(s) remaining, {exhausted_count} exhausted.",
                "warning",
            ))


async def _main(*, run_once: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    create_db_and_tables()
    settings = get_settings()
    worker = IngestionWorker(run_interval_seconds=settings.worker_interval_seconds)
    if run_once:
        await worker.run_once()
    else:
        await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Truth of Fun ingestion worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single ingestion cycle and exit (default: loop forever).",
    )
    args = parser.parse_args()
    asyncio.run(_main(run_once=args.once))


if __name__ == "__main__":
    main()
