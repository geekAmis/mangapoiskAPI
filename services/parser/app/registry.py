"""Adapter registry.

Adapters are instantiated once per process because they share an HTTP client,
a cache and a per-upstream rate limiter.  A source can be listed while still
being disabled; disabled sources deliberately resolve to a 404 so callers never
fall back to an unverified scraper by accident.
"""

from __future__ import annotations

import httpx
from manga_common.cache import Cache
from manga_common.config import Settings
from manga_common.errors import NotFoundError
from manga_common.source_models import SourceInfo

from .adapters.base import BaseAdapter
from .adapters.hentailib import HentaiLibAdapter
from .adapters.mangadex import MangaDexAdapter
from .adapters.mangalib import MangaLibAdapter
from .adapters.mangapoisk import MangaPoiskAdapter
from .adapters.readmanga import ReadMangaAdapter
from .adapters.remanga import RemangaAdapter


class AdapterRegistry:
    """Holds adapters keyed by their stable source code."""

    def __init__(self, adapters: list[BaseAdapter]) -> None:
        self._adapters: dict[str, BaseAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters[adapter.info.code] = adapter

    def get(self, code: str) -> BaseAdapter | None:
        return self._adapters.get((code or "").strip().lower())

    def require(self, code: str) -> BaseAdapter:
        normalised = (code or "").strip().lower()
        adapter = self._adapters.get(normalised)
        if adapter is None:
            raise NotFoundError(
                f"Unknown source '{code}'",
                code="source_not_found",
                details={"available": sorted(self._adapters)},
            )
        if not adapter.info.enabled:
            raise NotFoundError(
                f"Source '{normalised}' is disabled",
                code="source_disabled",
                details={
                    "source": normalised,
                    "notes": adapter.info.notes,
                    "available": sorted(
                        key for key, item in self._adapters.items() if item.info.enabled
                    ),
                },
            )
        return adapter

    def infos(self) -> list[SourceInfo]:
        return [adapter.info.model_copy(deep=True) for adapter in self._adapters.values()]

    def codes(self) -> list[str]:
        return list(self._adapters)

    @property
    def adapters(self) -> tuple[BaseAdapter, ...]:
        return tuple(self._adapters.values())


def build_registry(
    client: httpx.AsyncClient,
    settings: Settings,
    cache: Cache,
) -> AdapterRegistry:
    """Create all adapters, then apply the explicit opt-in source list."""

    adapters: list[BaseAdapter] = [
        MangaPoiskAdapter(client, settings, cache),
        MangaLibAdapter(client, settings, cache),
        RemangaAdapter(client, settings, cache),
        ReadMangaAdapter(client, settings, cache),
        MangaDexAdapter(client, settings, cache),
        HentaiLibAdapter(client, settings, cache),
    ]
    enabled = getattr(settings, "enabled_source_codes", set())
    if enabled:
        for adapter in adapters:
            if adapter.info.code in enabled:
                adapter.info.enabled = True
    return AdapterRegistry(adapters)
