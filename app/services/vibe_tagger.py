from __future__ import annotations

import re
from typing import Protocol

import anthropic

from app.core.config import get_settings
from app.services.tags import VIBE_VOCABULARY, canonical_vibe_tags


class VibeTagger(Protocol):
    async def generate_vibe_tags(self, description: str | None) -> list[str]:
        """Generate 3-5 vibe tags for an event description."""


class ClaudeVibeTagger:
    """LLM utility that derives concise vibe tags from event descriptions using Claude."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.anthropic_model
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key) if self._api_key else None

    async def generate_vibe_tags(self, description: str | None) -> list[str]:
        if self._client is None or not description or not description.strip():
            return []

        # An unconstrained prompt free-associates and the vocabulary explodes:
        # tags that appear once carry no ranking signal, and the profiles in
        # ``_INTENT_VIBE_PROFILES`` never match anything. Offer a closed menu.
        vocabulary = ", ".join(sorted(VIBE_VOCABULARY))
        prompt = (
            "Choose 3 to 5 vibe tags for the event description below.\n"
            "You MUST choose only from this list, copied exactly:\n"
            f"{vocabulary}\n\n"
            "Return only comma-separated tags and no explanations. If fewer than "
            "three fit, return only the ones that fit.\n\n"
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

        # Accept comma/newline-delimited output, then keep only recognised
        # vocabulary -- the model can still invent tags despite the prompt.
        chunks = re.split(r"[,|\n]+", raw_content)
        candidates = [
            re.sub(r"^[\-\d\.\)\s]+", "", chunk).strip()
            for chunk in chunks
            if chunk.strip()
        ]
        return canonical_vibe_tags(candidates)[:5]
