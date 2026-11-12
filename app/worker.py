from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import func, text, update
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.observability import init_error_reporting
from app.core.redaction import redact_secrets
from app.ingestion import registry
from app.models.event import Event
from app.models.source_health import SourceHealthRecord
from app.services.alerting import send_alert
from app.services.data_pipeline import DataPipelineService
from app.services.geocoding import build_geocoder
from app.services.key_usage_snapshots import snapshot_key_health
from app.services.regions import assign_missing_places
from app.services.secrets_store import get_secrets_store

logger = logging.getLogger(__name__)

# Module-level source health state, readable by the /health/sources endpoint.
_source_health_state: dict[str, dict[str, Any]] = {}

# Arbitrary but stable key for pg_try_advisory_lock: one ingestion cycle at a
# time across every worker process pointed at the same database.
_CYCLE_LOCK_KEY = 0x546F46_494E47  # "ToF" "ING"

#: Identical alerts are suppressed for this long. Without it a source that
#: stays broken re-pages the channel every cycle until people mute it.
_ALERT_COOLDOWN = timedelta(hours=24)


def heartbeat_path() -> Path:
    return Path(os.environ.get("WORKER_HEARTBEAT_FILE") or Path(tempfile.gettempdir()) / "tof-worker.heartbeat")


def touch_heartbeat() -> None:
    """Record that the worker made progress (see ``--healthcheck``)."""
    with suppress(OSError):
        path = heartbeat_path()
        path.touch()
        os.utime(path, None)


def heartbeat_age_seconds() -> float | None:
    try:
        return max(0.0, time.time() - heartbeat_path().stat().st_mtime)
    except OSError:
        return None


class CycleAlreadyRunning(RuntimeError):
    """Another worker holds the ingestion lock; this cycle was skipped."""


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
        source_timeout_seconds: float | None = None,
        lock_engine: Engine | None = None,
    ) -> None:
        settings = get_settings()
        # Hard ceiling on one source's fetch. A scraper waiting on a host that
        # never answers would otherwise stall every later source, the whole
        # cycle, and every cycle after it — silently.
        self._source_timeout_seconds = (
            source_timeout_seconds
            if source_timeout_seconds is not None
            else settings.worker_source_timeout_seconds
        )
        # Only a worker wired to a real database takes the cross-process
        # lock; unit tests drive the cycle with fakes and no engine.
        self._lock_engine = lock_engine
        self._alert_history: dict[tuple[str, str], datetime] = {}
        self._health_restored = False
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
            delay = float(self._run_interval_seconds)
            try:
                await self.run_once()
            except CycleAlreadyRunning:
                logger.warning(
                    "Another worker holds the ingestion lock; skipping this cycle."
                )
            except Exception:
                # A failed transaction or temporary dependency outage must not
                # terminate the scheduler. Cancellation (BaseException) still
                # exits promptly. Retry sooner than a full interval: a database
                # blip at 02:00 should not cost six hours of freshness.
                delay = min(delay, float(get_settings().worker_failure_retry_seconds))
                logger.exception("Ingestion cycle failed; retrying in %.0fs.", delay)
            await self._sleep_with_heartbeat(delay)

    @staticmethod
    async def _sleep_with_heartbeat(seconds: float) -> None:
        """Sleep in short slices so an idle worker still reads as alive."""
        remaining = float(seconds)
        touch_heartbeat()
        while remaining > 0:
            chunk = min(60.0, remaining)
            await asyncio.sleep(chunk)
            remaining -= chunk
            touch_heartbeat()

    @contextmanager
    def _cycle_lock(self) -> Iterator[None]:
        """Hold a session-level advisory lock for the duration of a cycle.

        Two workers (a deploy overlap, an operator running ``--once`` beside
        the loop) would otherwise crawl every source twice and race each other
        through the dedupe window, inserting duplicate events.
        """
        if self._lock_engine is None or self._lock_engine.dialect.name != "postgresql":
            yield
            return
        with self._lock_engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": _CYCLE_LOCK_KEY}
            ).scalar()
            connection.commit()
            if not acquired:
                raise CycleAlreadyRunning()
            try:
                yield
            finally:
                with suppress(Exception):
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": _CYCLE_LOCK_KEY}
                    )
                    connection.commit()

    async def run_once(self) -> WorkerRunResult:
        with self._cycle_lock():
            return await self._run_cycle()

    async def _run_cycle(self) -> WorkerRunResult:
        started_at = datetime.now(timezone.utc)
        touch_heartbeat()
        self._restore_health_state()
        self._assign_event_places()
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
            touch_heartbeat()
            budget: asyncio.Timeout | None = None
            try:
                source = self._registry.create(source_name)
                async with asyncio.timeout(self._source_timeout_seconds) as budget:
                    fetched_events = await source.fetch_events()
            except Exception as exc:
                if budget is not None and budget.expired():
                    # Our budget, not the source's own timeout (a Playwright
                    # navigation raising TimeoutError keeps its message below).
                    exc = TimeoutError(
                        f"source exceeded the {self._source_timeout_seconds:.0f}s "
                        "fetch budget and was cancelled"
                    )
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
                    # Closing a wedged browser can hang as surely as the
                    # fetch did; bound it too.
                    with suppress(Exception, asyncio.TimeoutError):
                        await asyncio.wait_for(source.close(), timeout=30)

            per_source_counts[source_name] = len(fetched_events)
            all_events.extend(fetched_events)
            source_runs.append((source_name, source, fetch_error))
            self._record_quota_health(
                source_name=source_name, used_key_id=getattr(source, "usage_key_id", None)
            )

        touch_heartbeat()
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
        self._assign_event_places()
        self._persist_source_health()
        await self._flush_alerts()
        touch_heartbeat()

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
        now = datetime.now(timezone.utc)
        for title, message, severity in pending:
            last_sent = self._alert_history.get((title, message))
            if last_sent is not None and now - last_sent < _ALERT_COOLDOWN:
                continue
            self._alert_history[(title, message)] = now
            with suppress(Exception):
                await send_alert(title=title, message=message, severity=severity)

    def _restore_health_state(self) -> None:
        """Reload persisted source health once per process.

        The canary baseline and the consecutive-zero ladder live in memory, so
        every restart (each deploy) used to reset them: a source that had been
        returning zero for days looked freshly "degraded", its last_success_at
        was overwritten with NULL, and the zero-result canary could not fire
        until five more cycles had rebuilt its history.
        """
        if self._health_restored:
            return
        self._health_restored = True
        try:
            with self._session_factory() as session:
                records = session.exec(select(SourceHealthRecord)).all()
        except Exception:
            logger.debug("Source health could not be restored; starting fresh.")
            return
        for record in records:
            if record.source_name in _source_health_state:
                continue
            _source_health_state[record.source_name] = {
                "last_run_at": record.last_run_at.isoformat() if record.last_run_at else None,
                "last_event_count": record.last_event_count,
                "status": record.status,
                "consecutive_zeros": record.consecutive_zeros,
                "last_error": record.last_error,
                "last_error_at": record.last_error_at.isoformat() if record.last_error_at else None,
                "last_success_at": (
                    record.last_success_at.isoformat() if record.last_success_at else None
                ),
            }
            history = self._source_count_history[record.source_name]
            if not history and record.last_event_count > 0 and record.consecutive_zeros == 0:
                history.append(record.last_event_count)

    def _assign_event_places(self) -> None:
        """Give city/region to any row that lacks them (see services/regions)."""
        try:
            with self._session_factory() as session:
                assigned = assign_missing_places(session)
            if assigned:
                logger.info("Assigned city/region to %s event(s).", assigned)
        except Exception:
            logger.debug("Event place assignment skipped (no database session).")

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
            # Not fatal for the cycle, but stale "scheduled" rows are visible
            # to users — make it visible to operators too.
            logger.warning("Lifecycle cleanup failed; past events were not marked.", exc_info=True)

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


def _require_migrated_schema() -> None:
    """Refuse to ingest into a database Alembic has not built.

    This used to call ``SQLModel.metadata.create_all``, which quietly produced
    a schema missing everything the migrations add in raw SQL (the full-text
    search column and trigger, expression indexes) — and then stamped nothing,
    so a later ``alembic upgrade head`` failed on "table already exists".
    """
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        raise SystemExit(
            "The database schema has not been created. Run `alembic upgrade head` "
            f"(or `make migrate`) before starting the worker. ({type(exc).__name__})"
        ) from None
    logger.info("Database schema at migration %s.", version)


def _start_watchdog(limit_seconds: float) -> None:
    """Exit the process if the ingestion loop stops making progress.

    asyncio timeouts cannot interrupt a blocking call that never yields to the
    event loop (a socket read with no timeout inside a client library). When
    that happens nothing in-process can recover, so exit non-zero and let the
    container's restart policy start a clean worker.
    """
    if limit_seconds <= 0:
        return

    def _watch() -> None:
        while True:
            time.sleep(30)
            age = heartbeat_age_seconds()
            if age is not None and age > limit_seconds:
                logger.critical(
                    "Worker made no progress for %.0fs (limit %.0fs); exiting for restart.",
                    age,
                    limit_seconds,
                )
                logging.shutdown()
                os._exit(70)

    threading.Thread(target=_watch, name="worker-watchdog", daemon=True).start()


def run_healthcheck() -> int:
    """Exit status for the container HEALTHCHECK: 0 while the worker is making progress."""
    limit = get_settings().worker_watchdog_seconds
    age = heartbeat_age_seconds()
    if age is None:
        print("unhealthy: no heartbeat has been written yet", file=sys.stderr)
        return 1
    if limit > 0 and age > limit:
        print(f"unhealthy: last progress {age:.0f}s ago (limit {limit}s)", file=sys.stderr)
        return 1
    print(f"healthy: last progress {age:.0f}s ago")
    return 0


async def _main(*, run_once: bool) -> None:
    configure_logging()
    init_error_reporting(component="worker")
    _require_migrated_schema()
    settings = get_settings()
    worker = IngestionWorker(
        run_interval_seconds=settings.worker_interval_seconds, lock_engine=engine
    )
    touch_heartbeat()
    if run_once:
        try:
            await worker.run_once()
        except CycleAlreadyRunning:
            raise SystemExit("Another ingestion worker is mid-cycle; not starting a second one.")
    else:
        _start_watchdog(settings.worker_watchdog_seconds)
        await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Truth of Fun ingestion worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single ingestion cycle and exit (default: loop forever).",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Exit 0 if a running worker has made progress recently, 1 otherwise.",
    )
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(run_healthcheck())
    asyncio.run(_main(run_once=args.once))


if __name__ == "__main__":
    main()
