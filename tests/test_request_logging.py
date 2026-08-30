"""Tests for request correlation, access logging, and unhandled-error capture.

These cover the operability promise in docs/operations.md: every request is
traceable by id, every failure leaves a logged traceback tied to that id, and
noisy health probes stay out of the access log.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware, _access_level
from app.core.logging import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    request_id_var,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        logging.getLogger("test.handler").info("inside handler")
        return {"ok": "yes"}

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    return app


def test_request_id_is_generated_and_echoed() -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/ok")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]


def test_inbound_request_id_is_preserved() -> None:
    """A proxy or client id must survive so traces correlate across hops."""
    with TestClient(_build_app()) as client:
        response = client.get("/ok", headers={REQUEST_ID_HEADER: "trace-abc-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc-123"


def test_unhandled_exception_returns_500_with_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash must produce a traceable body and a logged traceback, not a bare 500."""
    client = TestClient(_build_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    # The message must not leak the internal exception text to the caller...
    assert "kaboom" not in json.dumps(body)
    # ...but it must be in the log, with the traceback.
    assert any("kaboom" in record.getMessage() or record.exc_info for record in caplog.records)


def test_handler_logs_carry_the_request_id() -> None:
    """Log lines emitted inside a handler must be greppable by request id."""
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(getattr(record, "request_id", ""))

    handler = _Capture()
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        with TestClient(_build_app()) as client:
            response = client.get("/ok", headers={REQUEST_ID_HEADER: "req-xyz"})
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    assert response.status_code == 200
    assert "req-xyz" in captured


def test_request_id_context_is_reset_after_the_request() -> None:
    """A leaked context var would mislabel later, unrelated log lines."""
    with TestClient(_build_app()) as client:
        client.get("/ok", headers={REQUEST_ID_HEADER: "leaky"})

    assert request_id_var.get() == ""


@pytest.mark.parametrize(
    ("status_code", "path", "duration_ms", "expected"),
    [
        (500, "/events", 5.0, logging.ERROR),
        (404, "/events", 5.0, logging.WARNING),
        (200, "/events", 5000.0, logging.WARNING),  # slow requests surface
        (200, "/events", 5.0, logging.INFO),
        (200, "/health", 5.0, None),  # probe noise suppressed
        (500, "/health", 5.0, logging.ERROR),  # ...but not when it fails
    ],
)
def test_access_log_levels(
    status_code: int, path: str, duration_ms: float, expected: int | None
) -> None:
    assert (
        _access_level(
            status_code=status_code,
            path=path,
            duration_ms=duration_ms,
            slow_request_ms=1000,
        )
        == expected
    )


def test_json_formatter_emits_one_parsable_object_with_extras() -> None:
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET %s -> %s",
        args=("/events", 200),
        exc_info=None,
    )
    record.request_id = "abc123"
    record.http_status = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "GET /events -> 200"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "abc123"
    assert payload["http_status"] == 200
    assert payload["logger"] == "app.access"


def test_json_formatter_includes_the_traceback() -> None:
    try:
        raise ValueError("bad input")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="app",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: bad input" in payload["exception"]


def test_configure_logging_is_idempotent() -> None:
    """uvicorn's reloader imports the app twice; handlers must not stack."""
    configure_logging()
    first = len(logging.getLogger().handlers)
    configure_logging()

    assert len(logging.getLogger().handlers) == first == 1
