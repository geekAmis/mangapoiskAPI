from __future__ import annotations

import logging
from typing import Any

import httpx
from manga_common.config import Settings
from manga_common.errors import NotFoundError, UpstreamError
from manga_common.http import build_client
from manga_common.source_models import (
    ChapterDetail,
    MangaDetail,
    SourceHome,
    SourceInfo,
    SourceSearchResult,
)

logger = logging.getLogger(__name__)


class ParserClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = build_client(settings, base_url=settings.parser_url.rstrip("/"))
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self.client.headers["Accept"] = "application/json"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self.client.get(path, params=params, timeout=60.0)
        except httpx.HTTPError as exc:
            raise UpstreamError("Parser service is unavailable", details=str(exc)) from exc
        if response.status_code == 404:
            raise NotFoundError("Source item not found", details=response.text[:300])
        if response.status_code >= 400:
            raise UpstreamError(
                "Parser service returned an error",
                details={"status": response.status_code, "body": response.text[:500]},
            )
        return response.json()

    async def sources(self) -> list[SourceInfo]:
        data = await self._get("/internal/sources")
        return [SourceInfo.model_validate(item) for item in data]

    async def search(self, source: str, query: str, page: int = 1) -> SourceSearchResult:
        data = await self._get(
            "/internal/search", params={"source": source, "q": query, "page": page}
        )
        return SourceSearchResult.model_validate(data)

    async def manga(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> MangaDetail:
        data = await self._get(
            "/internal/manga",
            params={
                "source": source,
                "source_id": source_id,
                "url": url,
                "chapters_limit": 1000,
            },
        )
        return MangaDetail.model_validate(data)

    async def chapter(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> ChapterDetail:
        data = await self._get(
            "/internal/chapter",
            params={"source": source, "source_id": source_id, "url": url},
        )
        return ChapterDetail.model_validate(data)

    async def home(self, source: str) -> SourceHome:
        data = await self._get("/internal/home", params={"source": source})
        return SourceHome.model_validate(data)

    async def healthy(self) -> bool:
        try:
            response = await self.client.get("/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.aclose()
