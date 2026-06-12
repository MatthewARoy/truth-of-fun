"""Product-local timezone for user-facing time windows.

Events are stored in UTC, but "tonight" / "this weekend" are SF-local
concepts: an 8 PM PDT show is 03:00 UTC the next day.
"""

from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
