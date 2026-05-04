"""
Stub source base for planned integrations.

Use _StubSource when a source is planned but not yet implemented.
Real implementations: dothebay, sfstation, minnesotastreet, luma, eddies_list.
"""

from __future__ import annotations

from typing import Any

from app.ingestion.base import BaseSource


class _StubSource(BaseSource):
    """
    Shared no-op implementation for planned sources.

    These stubs let the registry and worker understand complete source coverage
    while connector implementation proceeds incrementally.
    """

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []
