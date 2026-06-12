"""Time presets must be computed in SF local time, not UTC.

An 8 PM PDT show is 03:00 UTC the next day; a UTC-midnight "tonight" window
ends at 4:59 PM local and misses every actual evening event.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.api.discovery import _apply_time_preset
from app.services.concierge import _resolve_timeframe_window

SF_TZ = ZoneInfo("America/Los_Angeles")


def test_tonight_preset_covers_the_sf_evening() -> None:
    # 6 PM PDT on Wed June 10 2026 == 01:00 UTC June 11
    now = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)
    start, end = _apply_time_preset(time_preset="tonight", now=now)

    assert start == now
    # An 8 PM PDT show tonight (03:00 UTC) must fall inside the window.
    show = datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc)
    assert start <= show <= end
    # The window ends in the SF early morning, not at UTC midnight.
    assert end.astimezone(SF_TZ).hour <= 4
    assert end > show


def test_weekend_preset_uses_sf_local_friday_evening() -> None:
    # Wednesday June 10 2026, noon PDT == 19:00 UTC
    now = datetime(2026, 6, 10, 19, 0, tzinfo=timezone.utc)
    start, end = _apply_time_preset(time_preset="this_weekend", now=now)

    start_local = start.astimezone(SF_TZ)
    end_local = end.astimezone(SF_TZ)
    assert (start_local.weekday(), start_local.hour) == (4, 17)  # Friday 5 PM local
    assert (end_local.weekday(), end_local.hour) == (0, 6)  # Monday 6 AM local

    # A Saturday 9 PM PDT show (Sunday 04:00 UTC) is inside the window.
    show = datetime(2026, 6, 14, 4, 0, tzinfo=timezone.utc)
    assert start <= show <= end


def test_concierge_tonight_window_is_sf_local() -> None:
    # 6 PM PDT on Wed June 10 2026 == 01:00 UTC June 11
    now = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)
    start, end = _resolve_timeframe_window("tonight", now=now)

    start_local = start.astimezone(SF_TZ)
    assert (start_local.month, start_local.day, start_local.hour) == (6, 10, 18)
    # 8 PM PDT tonight is inside the window.
    show = datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc)
    assert start <= show <= end


def test_concierge_saturday_window_is_sf_local() -> None:
    # Wednesday June 10 2026, noon PDT == 19:00 UTC; next Saturday is June 13.
    now = datetime(2026, 6, 10, 19, 0, tzinfo=timezone.utc)
    start, end = _resolve_timeframe_window("this_saturday", now=now)

    start_local = start.astimezone(SF_TZ)
    end_local = end.astimezone(SF_TZ)
    assert (start_local.month, start_local.day, start_local.hour) == (6, 13, 10)
    assert end_local.day == 14 and end_local.hour == 2
