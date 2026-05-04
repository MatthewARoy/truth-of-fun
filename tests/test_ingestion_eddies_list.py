"""Tests for Eddie's List source - NOT_TESTABLE without IMAP credentials."""

from __future__ import annotations

from app.ingestion.sources.eddies_list import EddiesListSource
from app.ingestion.sources.eddies_list import REQUIRES_IMAP_CREDENTIALS
from app.ingestion.sources.eddies_list import TESTABLE


def test_eddies_list_not_testable() -> None:
    assert TESTABLE is False
    assert REQUIRES_IMAP_CREDENTIALS is True


def test_eddies_list_returns_empty_without_credentials() -> None:
    import asyncio

    source = EddiesListSource()
    events = asyncio.run(source.fetch_events())
    assert events == []
