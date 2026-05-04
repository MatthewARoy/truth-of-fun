"""Tests for shared scraper utilities."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.ingestion.scraper_utils import (
    parse_12h_to_24h,
    parse_date_range,
    parse_datetime_flexible,
    parse_price,
    pick_first_str,
    strip_html_tags,
)


def test_strip_html_tags() -> None:
    assert strip_html_tags("<p>Hello</p>") == "Hello"
    assert strip_html_tags("<a href='x'>Link</a> text") == "Link text"
    assert strip_html_tags("  no tags  ") == "no tags"


def test_parse_12h_to_24h() -> None:
    assert parse_12h_to_24h(7, "pm") == 19
    assert parse_12h_to_24h(12, "pm") == 12
    assert parse_12h_to_24h(12, "am") == 0
    assert parse_12h_to_24h(9, "am") == 9


def test_parse_price() -> None:
    assert parse_price("Free") == (0.0, True)
    assert parse_price("Starts at $20") == (20.0, False)
    assert parse_price("$15.00") == (15.0, False)
    assert parse_price("") == (None, False)


def test_parse_datetime_flexible() -> None:
    dt = parse_datetime_flexible("2026-03-02 7:15 pm")
    assert dt is not None
    assert dt.month == 3
    assert dt.day == 2
    assert dt.hour == 19
    assert dt.minute == 15


def test_parse_date_range() -> None:
    start, end = parse_date_range("Feb 14–Mar 28, 2026")
    assert start is not None
    assert end is not None
    assert start.month == 2
    assert start.day == 14
    assert end.month == 3
    assert end.day == 28


def test_pick_first_str() -> None:
    assert pick_first_str({"a": "x", "b": "y"}, "c", "a") == "x"
    assert pick_first_str({"a": "", "b": "y"}, "a", "b") == "y"
    assert pick_first_str({}, "a") is None
