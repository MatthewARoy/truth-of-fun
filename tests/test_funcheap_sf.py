"""Tests for FuncheapSF scraper date parsing and cost extraction."""

from datetime import date, datetime, timezone

from app.ingestion.sources.funcheap_sf import FuncheapSFSource


def test_parse_absolute_date_to_iso8601_utc() -> None:
    """Absolute date parses and converts to ISO 8601 UTC with exact start and end."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time(
        "Sunday, March 1, 2026 - 7:00 pm to 9:30 pm | Cost: FREE",
        "Sunday, March 1, 2026 - 7:00 pm to 9:30 pm",
    )
    # March 1, 2026 is before DST starts, so PST (UTC-8): 7:00pm = 3:00am UTC next day
    assert start == datetime(2026, 3, 2, 3, 0, tzinfo=timezone.utc)
    # End must be the real 9:30pm, not a copy of the start time
    assert end == datetime(2026, 3, 2, 5, 30, tzinfo=timezone.utc)


def test_parse_end_time_without_minutes() -> None:
    """'7pm to 10pm' style (no minutes) parses a distinct end time."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time(
        "Saturday, March 14, 2026 - 7pm to 10pm | Cost: $10",
        "Saturday, March 14, 2026 - 7pm to 10pm",
    )
    # March 14, 2026 is after DST starts, so PDT (UTC-7)
    assert start == datetime(2026, 3, 15, 2, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 15, 5, 0, tzinfo=timezone.utc)


def test_parse_end_time_past_midnight_rolls_to_next_day() -> None:
    """An end time earlier than the start rolls to the next day."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time(
        "Friday, March 13, 2026 - 10:00 pm to 1:30 am",
        "Friday, March 13, 2026 - 10:00 pm to 1:30 am",
    )
    # 10:00pm PDT March 13 = 5:00am UTC March 14; 1:30am next day PDT = 8:30am UTC March 14
    assert start == datetime(2026, 3, 14, 5, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 14, 8, 30, tzinfo=timezone.utc)


def test_no_parseable_date_drops_event() -> None:
    """No date evidence => return None, never fabricate a 'today' date."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time("Some random page text with no date", "")
    assert start is None
    assert end is None


def test_time_only_without_date_drops_event() -> None:
    """A bare time with no date is not date evidence - the event must be dropped."""
    source = FuncheapSFSource(proxy=None)
    start, end = source._parse_date_and_time(
        "Doors at 7:00 pm | Cost: FREE", "Doors at 7:00 pm"
    )
    assert start is None
    assert end is None


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


def test_parse_live_detail_block_single_time() -> None:
    """The live single-line detail block ('<date> - <time> | Cost: ...') parses."""
    source = FuncheapSFSource(proxy=None)
    # Shape of the real ".cost"-container block scraped from sf.funcheap.com.
    block = (
        "Monday, June 15, 2026 - 6:00 pm | Cost: FREE Book Passage (Corte Madera) "
        "| 51 Tamal Vista Blvd. Corte Madera, CA Corte MaderaNorth Bay"
    )
    start, end = source._parse_date_and_time(block, block)
    # June 15, 2026 is PDT (UTC-7): 6:00pm = 1:00am UTC next day. No end time given.
    assert start == datetime(2026, 6, 16, 1, 0, tzinfo=timezone.utc)
    assert end is None


def test_parse_live_detail_block_with_time_range() -> None:
    """The live detail block with a 'to' time range parses a distinct end time."""
    source = FuncheapSFSource(proxy=None)
    block = (
        "Saturday, June 20, 2026 - 11:00 am to 3:30 pm | Cost: FREE One Market Plaza "
        "| 1 Market Street, San Francisco, CA Financial DistrictSan Francisco"
    )
    start, end = source._parse_date_and_time(block, block)
    # June 20, 2026 is PDT (UTC-7): 11:00am = 6:00pm UTC; 3:30pm = 10:30pm UTC.
    assert start == datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 20, 22, 30, tzinfo=timezone.utc)


def test_extract_address_from_detail_block() -> None:
    """A street address embedded in the detail block is extracted verbatim."""
    source = FuncheapSFSource(proxy=None)
    block = (
        "Monday, June 15, 2026 - 7:00 pm to 2:00 am | Cost: FREE* Madrone Art Bar "
        "| 500 Divisadero Street, San Francisco, CA 94117 NoPaSan Francisco"
    )
    assert (
        source._extract_address(block)
        == "500 Divisadero Street, San Francisco, CA 94117"
    )


def test_extract_address_none_when_no_street() -> None:
    """No street address in the block => None, never fabricated."""
    source = FuncheapSFSource(proxy=None)
    assert source._extract_address("Monday, June 15, 2026 - 7:00 pm | Cost: FREE") is None
    assert source._extract_address("") is None
