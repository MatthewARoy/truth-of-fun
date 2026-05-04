from __future__ import annotations

import re
from typing import Protocol

import anthropic

from app.core.config import get_settings


class VibeTagger(Protocol):
    async def generate_vibe_tags(self, description: str | None) -> list[str]:
        """Generate 3-5 vibe tags for an event description."""


class ClaudeVibeTagger:
    """LLM utility that derives concise vibe tags from event descriptions using Claude."""

    def __init__(self, *, api_key: str | None = None, model: str = "claude-haiku-4-5-20250901") -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key) if self._api_key else None

    async def generate_vibe_tags(self, description: str | None) -> list[str]:
        if self._client is None or not description or not description.strip():
            return []

        prompt = (
            "Generate 3 to 5 short vibe tags for the event description below. "
            "Return only comma-separated tags, each beginning with # and no explanations.\n\n"
            f"Description:\n{description.strip()}"
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
                system="You generate concise vibe tags for events.",
            )
        except Exception:
            return []

        content = response.content[0].text if response.content else ""
        return self._normalize_tags(content)

    def _normalize_tags(self, raw_content: str | None) -> list[str]:
        if not raw_content:
            return []

        # Accept comma/newline-delimited output and normalize into hashtag tokens.
        chunks = re.split(r"[,|\n]+", raw_content)
        normalized: list[str] = []
        for chunk in chunks:
            cleaned = chunk.strip()
            if not cleaned:
                continue
            cleaned = re.sub(r"^[\-\d\.\)\s]+", "", cleaned).strip()
            if not cleaned:
                continue

            if not cleaned.startswith("#"):
                cleaned = "#" + re.sub(r"\s+", "", cleaned)
            else:
                cleaned = "#" + re.sub(r"\s+", "", cleaned[1:])

            if len(cleaned) <= 1:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)

        return normalized[:5]
