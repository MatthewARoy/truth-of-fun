from typing import Any

from app.ingestion.base import BaseSource


class SourceRegistry:
    """Registry for ingestion source provider classes."""

    def __init__(self) -> None:
        self._providers: dict[str, type[BaseSource]] = {}

    def register(self, name: str, provider: type[BaseSource]) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Provider name must not be empty.")
        if normalized in self._providers:
            raise ValueError(f"Provider '{normalized}' is already registered.")
        self._providers[normalized] = provider

    def get(self, name: str) -> type[BaseSource]:
        normalized = name.strip().lower()
        if normalized not in self._providers:
            raise KeyError(f"Provider '{normalized}' is not registered.")
        return self._providers[normalized]

    def create(self, name: str, **kwargs: Any) -> BaseSource:
        provider = self.get(name)
        return provider(**kwargs)

    def list_sources(self) -> list[str]:
        return sorted(self._providers.keys())
