"""Scrub credentials out of text before it leaves the process.

Exception messages are a classic credential leak: psycopg2 puts the connection
DSN in its errors, httpx puts the full request URL in its own, and both may
carry a password or an API key. Those strings reach two places we do not fully
control — the ``source_health.last_error`` column, which ``GET /health/sources``
serves publicly, and the readiness probe's body.

This module is a safety net, not a licence to log secrets deliberately.
"""

from __future__ import annotations

import re

_REDACTED = "[redacted]"

# scheme://user:password@host -> scheme://[redacted]@host
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")

# Sensitive query parameters and key=value pairs, however they're punctuated.
_SENSITIVE_KEY = (
    r"(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|token|password|passwd|"
    r"pwd|secret|client[_-]?secret|authorization|auth)"
)
_KEY_VALUE = re.compile(
    rf"(?i)\b{_SENSITIVE_KEY}\b(\s*[=:]\s*|\s+)([\"']?)([^\s,;&\"']+)\2"
)

# Bearer tokens in any surrounding text.
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")

# A JWT's segments are individually short enough to slip past _OPAQUE_TOKEN,
# so match the dotted three-part shape directly.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")

# Long opaque strings that look like keys even without a label. Deliberately
# conservative (32+ chars) so ordinary prose survives.
_OPAQUE_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def redact_secrets(text: str | None) -> str | None:
    """Return ``text`` with anything that looks like a credential removed."""
    if not text:
        return text

    # Order matters: the labelled-value rule would otherwise consume the
    # "Authorization:" prefix and leave the token itself in place.
    redacted = _BEARER.sub(f"Bearer {_REDACTED}", text)
    redacted = _JWT.sub(_REDACTED, redacted)
    redacted = _URL_CREDENTIALS.sub(_REDACTED, redacted)
    redacted = _KEY_VALUE.sub(lambda m: f"{m.group(0).split(m.group(1))[0]}={_REDACTED}", redacted)
    redacted = _OPAQUE_TOKEN.sub(_REDACTED, redacted)
    return redacted


def describe_exception(exc: BaseException, *, include_message: bool) -> str:
    """Render an exception for an operator.

    ``include_message`` is False on any publicly reachable surface outside
    development: the exception *type* is nearly always enough to act on
    ("OperationalError", "TimeoutError") while the message is where hosts,
    ports, paths, and credentials hide. The full message is still logged
    server-side.
    """
    if not include_message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {redact_secrets(str(exc))}"
