"""Logging configuration shared by the API and the ingestion worker.

Both processes call :func:`configure_logging` once at startup so their output
has the same shape. Two formats are available, selected by the ``LOG_FORMAT``
setting:

``text``
    Human-readable, for `make api` / `make worker` in a terminal.

``json``
    One JSON object per line, for `docker compose logs` piped into `jq` or
    shipped to a log aggregator. This is the format the operations runbook
    (`docs/operations.md`) assumes.

Every record carries the current request id when one is in scope, so a single
API request's log lines — including the traceback of anything it raised — can
be grepped out by that one value.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

#: Set by the API's request-context middleware; empty in the worker.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Attributes present on every LogRecord. Anything else was attached by the
# caller via `extra=` and belongs in the structured payload.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"asctime", "message", "taskName"}


class RequestIdFilter(logging.Filter):
    """Stamp every record with the ambient request id (empty string if none)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id

        # Caller-supplied `extra=` fields, so structured context (event counts,
        # source names, durations) survives into the aggregator.
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key == "request_id":
                continue
            payload[key] = _jsonable(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable format with the request id appended when present."""

    default_fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.default_fmt)

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        request_id = getattr(record, "request_id", "")
        if request_id:
            formatted = f"{formatted} [request_id={request_id}]"
        return formatted


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def configure_logging(*, level: str | None = None, fmt: str | None = None) -> None:
    """Install a single stdout handler on the root logger.

    Idempotent: repeated calls replace the handler rather than stacking
    duplicates (uvicorn's reloader imports the app module more than once).
    """
    from app.core.config import get_settings

    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    resolved_format = (fmt or settings.log_format).lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if resolved_format == "json" else TextFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved_level)

    # uvicorn installs its own handlers; drop them so lines aren't emitted
    # twice in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # The access log is served by our own middleware, which records durations
    # and request ids that uvicorn's line does not have.
    logging.getLogger("uvicorn.access").disabled = True
