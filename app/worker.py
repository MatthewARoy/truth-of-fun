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
from app.core.logging import configure_logging
from app.core.redaction import redact_secrets
from app.ingestion import registry
from app.models.event import Event
from app.models.source_health import SourceHealthRecord
from app.services.alerting import send_alert
from app.services.data_pipeline import DataPipelineService
from app.services.geocoding import build_geocoder
from app.services.key_usage_snapshots import snapshot_key_health
from app.services.secrets_store import get_secrets_store

logger = logging.getLogger(__name__)

# Module-level source health state, readable by the /health/sources endpoint.
_source_health_state: dict[str, dict[str, Any]] = {}


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO timestamp from the in-memory health state, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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
        self._pipeline_service = pipeline_service or DataPipelineService(
            geocoder=build_geocoder()
        )
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
            try:
                await self.run_once()
            except Exception:
                # A failed transaction or temporary dependency outage must not
                # terminate the scheduler. Cancellation (BaseException) still
                # exits promptly; retry only after the normal interval.
                logger.exception("Ingestion cycle failed; retrying after the configured interval.")
            await asyncio.sleep(self._run_interval_seconds)

    async def run_once(self) -> WorkerRunResult:
        started_at = datetime.now(timezone.utc)
        all_events: list[dict[str, Any]] = []
        per_source_counts: dict[str, int] = {}
        source_runs: list[tuple[str, SourceLike | None, str | None]] = []

        # Roll over quota windows before fetching so a key whose daily cap has
        # reset is available again for this run.
        self._reset_quota_exhausted_keys()

        for source_name in self._registry.list_sources():
            source: SourceLike | None = None
            fetched_events: list[dict[str, Any]] = []
            fetch_error: str | None = None
            try:
                source = self._registry.create(source_name)
                fetched_events = await source.fetch_events()
            except Exception as exc:
                # Keep the type as well as the message: "TimeoutError" and
                # "403 Forbidden" call for very different fixes, and the
                # message alone often omits the class. Redact before storing —
                # this string is served by GET /health/sources, and scraper
                # exceptions routinely carry the full request URL.
                fetch_error = (
                    f"{type(exc).__name__}: {redact_secrets(str(exc))}"
                )[:1000]
                logger.exception(
                    "Source '%s' failed during fetch.",
                    source_name,
                    extra={"source_name": source_name, "outcome": "fetch_failed"},
                )
            finally:
                if source is not None:
                    # A source that recovered from a partial failure returns
                    # normally but records it here; without this a half-read
                    # Ticketmaster window looks like a healthy small result.
                    if fetch_error is None:
                        partial = getattr(source, "last_fetch_error", None)
                        if partial:
                            fetch_error = redact_secrets(str(partial))[:1000]
                            logger.warning(
                                "Source '%s' completed with a partial failure: %s",
                                source_name,
                                fetch_error,
                                extra={
                                    "source_name": source_name,
                                    "outcome": "partial_fetch",
                                },
                            )
                    with suppress(Exception):
                        await source.close()

            per_source_counts[source_name] = len(fetched_events)
            all_events.extend(fetched_events)
            source_runs.append((source_name, source, fetch_error))
            self._record_quota_health(
                source_name=source_name, used_key_id=getattr(source, "usage_key_id", None)
            )

        try:
            with self._session_factory() as session:
                pipeline_summary = await self._pipeline_service.process_raw_events(
                    session=session,
                    raw_events=all_events,
                )
        except Exception as exc:
            failure = f"Pipeline {type(exc).__name__}: {redact_secrets(str(exc))}"[:1000]
            for source_name, _source, fetch_error in source_runs:
                self._log_canary_metrics(
                    source_name=source_name,
                    current_count=per_source_counts[source_name],
                    error=f"{fetch_error}; {failure}"[:1000] if fetch_error else failure,
                )
            logger.exception("Ingestion pipeline failed; source checkpoints retained for replay.")
            self._pending_alerts.append(("Ingestion pipeline failed", failure, "critical"))
            self._persist_source_health()
            await self._flush_alerts()
            raise

        rejected = pipeline_summary.get("rejected", 0)
        for source_name, source, fetch_error in source_runs:
            if rejected and fetch_error is None:
                # Batch rejection attribution is not available: conservatively
                # retain every checkpoint rather than skipping an invalid row.
                fetch_error = f"Pipeline rejected {rejected} event(s); checkpoint retained for replay"
            acknowledge = getattr(source, "acknowledge_persisted", None)
            if fetch_error is None and callable(acknowledge):
                try:
                    acknowledge()
                except Exception as exc:
                    fetch_error = f"Checkpoint {type(exc).__name__}: {redact_secrets(str(exc))}"[:1000]
                    logger.exception("Could not save source '%s' checkpoint.", source_name)
            self._log_canary_metrics(
                source_name=source_name,
                current_count=per_source_counts[source_name],
                error=fetch_error,
                empty_is_success=bool(getattr(source, "last_fetch_was_incremental", False)),
                empty_reason=getattr(source, "last_empty_reason", None),
            )
            if fetch_error:
                self._pending_alerts.append((f"Source {source_name} incomplete", fetch_error, "warning"))

        self._mark_past_events()
        self._persist_source_health()
        await self._flush_alerts()

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

    async def _flush_alerts(self) -> None:
        pending, self._pending_alerts = self._pending_alerts, []
        for title, message, severity in pending:
            with suppress(Exception):
                await send_alert(title=title, message=message, severity=severity)

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
                        last_run_at=_parse_iso(last_run_at),
                        last_error=state.get("last_error"),
                        last_error_at=_parse_iso(state.get("last_error_at")),
                        last_success_at=_parse_iso(state.get("last_success_at")),
                    )
                    session.merge(record)
                session.commit()
        except Exception:
            logger.warning("Source health could not be persisted.", exc_info=True)

    def _log_canary_metrics(
        self, *, source_name: str, current_count: int, error: str | None = None,
        empty_is_success: bool = False,
        empty_reason: str | None = None,
    ) -> None:
        history = self._source_count_history[source_name]
        historic_avg = (sum(history) / len(history)) if history else 0.0

        logger.info(
            "Canary metric source=%s events_fetched=%s historic_avg=%.2f",
            source_name,
            current_count,
            historic_avg,
            extra={
                "source_name": source_name,
                "events_fetched": current_count,
                "historic_avg": round(historic_avg, 2),
            },
        )

        if history and historic_avg > 10 and current_count == 0 and not empty_is_success:
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
        if current_count == 0 and not (empty_is_success and error is None):
            consecutive_zeros += 1
        else:
            consecutive_zeros = 0

        # An exception is a harder signal than a zero count: report it as
        # failing on the first occurrence rather than waiting for the
        # consecutive-zero ladder to escalate.
        if error is not None:
            status = "failing"
        elif consecutive_zeros == 0:
            status = "healthy"
        elif consecutive_zeros == 1:
            status = "degraded"
        else:
            status = "failing"

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        diagnostic = error
        if current_count == 0 and not empty_is_success:
            diagnostic = error or redact_secrets(empty_reason) or "Empty result: source returned no events and no specific diagnostic"
            logger.warning("Source '%s' yielded zero events: %s", source_name, diagnostic)
        _source_health_state[source_name] = {
            "last_run_at": now_iso,
            "last_event_count": current_count,
            "status": status,
            "consecutive_zeros": consecutive_zeros,
            # A successful run clears the error so a recovered source doesn't
            # keep displaying a stale failure; last_error_at/last_success_at
            # preserve the history either way.
            "last_error": diagnostic,
            "last_error_at": now_iso if diagnostic is not None else prev.get("last_error_at"),
            "last_success_at": (
                now_iso if error is None and (current_count > 0 or empty_is_success)
                else prev.get("last_success_at")
            ),
        }

    def _reset_quota_exhausted_keys(self) -> None:
        """Auto-reactivate AAIM keys whose quota window has rolled over.

        Replaces the manual redis-cli recovery: exhausted keys come back on
        their own once ``aaim_quota_window_hours`` have passed.
        """
        if not get_settings().aaim_enabled or self._quota_window_hours <= 0:
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

    def _record_quota_health(self, *, source_name: str, used_key_id: str | None = None) -> None:
        if source_name != "ticketmaster" or not get_settings().aaim_enabled:
            return
        try:
            key_health = get_secrets_store().health("ticketmaster")
        except Exception:
            return
        if not key_health:
            if used_key_id == "env-ticketmaster":
                logger.warning("AAIM: environment Ticketmaster key used; shared quota telemetry unavailable (check Redis).")
            elif used_key_id:
                logger.warning("AAIM: Ticketmaster key '%s' used but quota telemetry unavailable.", used_key_id)
            else:
                logger.warning("AAIM quota health: no usable Ticketmaster key was selected.")
            return

        # Provider calls were already spent even if event persistence fails.
        # Reuse the cycle's quota read, recording only the key this source used.
        used_health = [item for item in key_health if getattr(item, "key_id", None) == used_key_id]
        if used_key_id and used_health:
            try:
                with self._session_factory() as session:
                    snapshot_key_health(provider=source_name, health_items=used_health, session=session)
            except Exception:
                logger.warning("Worker API-key usage snapshot could not be recorded.", exc_info=True)

        managed_inventory = any(getattr(item, "key_id", "") != "env-ticketmaster" for item in key_health)
        active_count = sum(
            1 for item in key_health if item.status == "active"
            and not (managed_inventory and getattr(item, "key_id", "") == "env-ticketmaster")
        )
        exhausted_count = sum(1 for item in key_health if item.status == "exhausted"
            and not (managed_inventory and getattr(item, "key_id", "") == "env-ticketmaster"))
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
    configure_logging()
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
