"""Credentials must not escape through health endpoints or persisted errors.

Exception messages are a classic leak: psycopg2 embeds the connection DSN,
httpx embeds the request URL. Both are served publicly via /health/*.
"""

from __future__ import annotations

import pytest

from app.core.redaction import describe_exception, redact_secrets


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        (
            "could not connect to postgresql://admin:s3cr3tpassword@db.internal:5432/tof",
            "s3cr3tpassword",
        ),
        (
            "GET https://app.ticketmaster.com/discovery/v2/events?apikey=AbCdEf123456 failed",
            "AbCdEf123456",
        ),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig rejected", "eyJhbGciOiJIUzI1NiJ9"),
        ("login failed for password=hunter2hunter2", "hunter2hunter2"),
        ("client_secret: abcdefghijklmnop rejected", "abcdefghijklmnop"),
    ],
)
def test_redact_removes_credentials(raw: str, must_not_contain: str) -> None:
    redacted = redact_secrets(raw)

    assert redacted is not None
    assert must_not_contain not in redacted


def test_redact_preserves_the_diagnostic_parts() -> None:
    """Redaction must not destroy the information an operator needs."""
    redacted = redact_secrets(
        "could not connect to postgresql://admin:hunter2@db.internal:5432/tof"
    )

    assert redacted is not None
    assert "could not connect" in redacted
    assert "db.internal:5432" in redacted


def test_redact_leaves_ordinary_messages_alone() -> None:
    message = "page.goto exceeded 30000ms while loading the events calendar"

    assert redact_secrets(message) == message


def test_redact_handles_none_and_empty() -> None:
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


def test_describe_exception_hides_the_message_when_not_public() -> None:
    """Outside development the type alone is published; the message is logged."""
    exc = RuntimeError("connection to postgresql://u:pw@host/db failed")

    assert describe_exception(exc, include_message=False) == "RuntimeError"


def test_describe_exception_redacts_even_when_detail_is_allowed() -> None:
    exc = RuntimeError("connection to postgresql://u:supersecret@host/db failed")

    described = describe_exception(exc, include_message=True)

    assert described.startswith("RuntimeError: ")
    assert "supersecret" not in described
