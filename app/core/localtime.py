"""Product-local timezone for user-facing time windows.

Events are stored in UTC, but "tonight" / "this weekend" are SF-local
concepts: an 8 PM PDT show is 03:00 UTC the next day.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def weekend_window(now: datetime) -> tuple[datetime, datetime]:
    """Remaining current weekend, or the next Friday 17:00–Monday 06:00."""
    local = now.astimezone(LOCAL_TZ)
    friday = (local - timedelta(days=(local.weekday() - 4) % 7)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    monday = (friday + timedelta(days=3)).replace(hour=6)
    if local >= monday:
        friday += timedelta(days=7)
        monday += timedelta(days=7)
    return max(local, friday).astimezone(timezone.utc), monday.astimezone(timezone.utc)


def tonight_end(now: datetime) -> datetime:
    """Before 03:00, tonight still refers to the night already underway."""
    local = now.astimezone(LOCAL_TZ)
    end = local.replace(hour=3, minute=0, second=0, microsecond=0)
    if local >= end:
        end += timedelta(days=1)
    return end.astimezone(timezone.utc)
