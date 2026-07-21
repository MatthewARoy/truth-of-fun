"""HTTP middleware: request correlation, access logging, and error capture.

The API previously emitted only uvicorn's default access line, which carries
no request id, no duration, and — critically — no record of *which* request
raised an unhandled exception. This module makes every request traceable:

1. Each request gets an id (honouring an inbound ``X-Request-ID`` so a proxy
   or client can correlate across hops) which is bound to a context variable,
   stamped on every log line emitted while handling it, and echoed back on the
   response.
2. One access line per request at completion, with status and duration.
   Server errors log at ERROR, client errors and slow requests at WARNING,
   everything else at INFO — so ``| grep -v INFO`` is a usable triage filter.
3. Unhandled exceptions are logged with a full traceback *and* the request id,
   then returned as a stable JSON body instead of a bare 500 with no clue in it.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings
from app.core.logging import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"

# Health probes run every few seconds per container; logging them at INFO
# drowns the signal. They still log at WARNING/ERROR when they actually fail.
_QUIET_PATHS = frozenset({"/health", "/health/live", "/health/ready"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._slow_request_ms = get_settings().log_slow_request_ms

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            # exception() rather than error() so the traceback lands in the log
            # next to the request id that produced it.
            logger.exception(
                "Unhandled error %s %s after %.1fms",
                request.method,
                request.url.path,
                duration_ms,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "duration_ms": round(duration_ms, 1),
                    "outcome": "unhandled_exception",
                },
            )
            request_id_var.reset(token)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error.",
                    "request_id": request_id,
                },
                headers={REQUEST_ID_HEADER: request_id},
            )

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id

        level = _access_level(
            status_code=response.status_code,
            path=request.url.path,
            duration_ms=duration_ms,
            slow_request_ms=self._slow_request_ms,
        )
        if level is not None:
            logger.log(
                level,
                "%s %s -> %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                },
            )

        request_id_var.reset(token)
        return response


def _access_level(
    *,
    status_code: int,
    path: str,
    duration_ms: float,
    slow_request_ms: int,
) -> int | None:
    """Pick the log level for an access line, or None to skip logging it."""
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    if duration_ms >= slow_request_ms:
        return logging.WARNING
    if path in _QUIET_PATHS:
        return None
    return logging.INFO
