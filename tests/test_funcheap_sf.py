"""Tests for FuncheapSF scraper date parsing and cost extraction."""

from datetime import date, datetime, timezone

from app.ingestion.sources.funcheap_sf import FuncheapSFSource


def test_parse_absolute_date_to_iso8601_utc() -> None:
    """Absolute date parses and converts to ISO 8601 UTC."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time(
        "Sunday, March 1, 2026 - 7:00 pm to 9:30 pm | Cost: FREE",
        "Sunday, March 1, 2026 - 7:00 pm to 9:30 pm",
    )
    assert start is not None
    assert start.tzinfo == timezone.utc
    assert start.year == 2026 and start.month == 3
    assert start.hour in (2, 3)  # 7pm PST = 3am UTC (or 2am when DST)
    assert end is not None
    assert end.tzinfo == timezone.utc


def test_parse_absolute_date() -> None:
    """Absolute date 'Sunday, March 1, 2026' parses correctly."""
    source = FuncheapSFSource(proxy=None)
    result = source._parse_absolute_date("Sunday, March 1, 2026")
    assert result == date(2026, 3, 1)

    result2 = source._parse_absolute_date("March 15, 2026")
    assert result2 == date(2026, 3, 15)


def test_parse_cost_free() -> None:
    """Cost 'FREE*' extracts as 0.0 USD."""
    source = FuncheapSFSource(proxy=None)
    price, currency = source._parse_cost("Cost: FREE*")
    assert price == 0.0
    assert currency == "USD"


def test_parse_cost_dollar() -> None:
    """Cost '$40*' extracts numeric price."""
    source = FuncheapSFSource(proxy=None)
    price, currency = source._parse_cost("$40*")
    assert price == 40.0
    assert currency == "USD"


def test_parse_cost_decimal() -> None:
    """Cost '$25.50' extracts decimal price."""
    source = FuncheapSFSource(proxy=None)
    price, currency = source._parse_cost("$25.50")
    assert price == 25.5
    assert currency == "USD"
