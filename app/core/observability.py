"""Optional error reporting.

Logs answer "what happened to this request"; an error tracker answers "what is
breaking right now, how often, and since which release" without anyone reading
logs. It is opt-in: with ``SENTRY_DSN`` unset nothing is imported, initialised
or sent, so local and OSS use never phone home.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def init_error_reporting(*, component: str) -> bool:
    """Initialise Sentry for this process if configured. Returns whether it is on."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; error reporting is off.")
        return False

    def _scrub(event: dict, _hint: dict) -> dict:
        # Share, invite and folder tokens are bearer credentials carried in
        # the URL path; keep only the method so a report cannot leak one.
        request = event.get("request")
        if isinstance(request, dict):
            event["request"] = {"method": request.get("method")}
        return event

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        before_send=_scrub,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Request bodies, cookies and auth headers stay out of reports: they
        # carry passwords, JWTs and share tokens.
        send_default_pii=False,
        max_request_body_size="never",
    )
    sentry_sdk.set_tag("component", component)
    logger.info("Error reporting enabled for %s.", component)
    return True
