from __future__ import annotations

from typing import Any

import httpx
from manga_common.config import Settings
from manga_common.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    UpstreamError,
    ValidationError,
)
from manga_common.http import build_client
from manga_common.schemas import (
    BookmarkOut,
    ChapterDetailOut,
    ChapterOut,
    ExportJobOut,
    HomeUpdatesOut,
    MangaDetailOut,
    MangaListResponse,
    MangaOut,
    MangaVariantsOut,
    ProgressOut,
    ReaderSettings,
    SourceOut,
    TokenPair,
    UserOut,
)
from manga_common.source_models import MangaSummary, SourceInfo

from .routing import Endpoint, EndpointPool, current_client_key


class InternalClient:
    service_code = ""

    def __init__(
        self,
        settings: Settings,
        base_url: str,
        *,
        pool: EndpointPool | None = None,
    ) -> None:
        self.config = settings
        self.client = build_client(settings, base_url=base_url.rstrip("/"))
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self.client.headers["Accept"] = "application/json"
        self.pool = pool

    def _candidates(self, method: str) -> list[Endpoint]:
        if self.pool is not None:
            chosen = self.pool.choose(self.service_code, current_client_key(), method)
            if chosen:
                return chosen
        return [
            Endpoint(
                server_id="static",
                server_name="static",
                url=str(self.client.base_url).rstrip("/"),
                healthy=True,
            )
        ]

    def _raise_for_response(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        code = "upstream_error"
        message = "Internal service returned an error"
        details: Any = {"status": response.status_code, "body": response.text[:500]}
        try:
            payload = response.json()
            error = payload.get("error", {})
            code = error.get("code") or code
            message = error.get("message") or message
            details = error.get("details") or details
        except ValueError:
            pass
        mapping = {
            400: ValidationError,
            401: UnauthorizedError,
            403: ForbiddenError,
            404: NotFoundError,
            409: ConflictError,
            422: ValidationError,
            429: RateLimitError,
        }
        error_cls = mapping.get(response.status_code)
        if error_cls is not None:
            raise error_cls(message, code=code, details=details)
        raise UpstreamError(message, details=details)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        candidates = self._candidates(method)
        last_error: Exception | None = None
        for index, endpoint in enumerate(candidates):
            try:
                response = await self.client.request(
                    method,
                    f"{endpoint.url}{path}",
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if self.pool is not None:
                    self.pool.mark_down(self.service_code, endpoint.server_id)
                continue
            if response.status_code >= 500 and index < len(candidates) - 1:
                last_error = UpstreamError(
                    "Service is unavailable",
                    details=f"{endpoint.url}: HTTP {response.status_code}",
                )
                if self.pool is not None:
                    self.pool.mark_down(self.service_code, endpoint.server_id)
                continue
            self._raise_for_response(response)
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise UpstreamError("Service is unavailable", details=str(last_error))

    def set_base_url(self, base_url: str) -> None:
        self.client.base_url = httpx.URL(base_url.rstrip("/"))

    async def stream(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        candidates = self._candidates("GET")
        last_error: Exception | None = None
        for index, endpoint in enumerate(candidates):
            request = self.client.build_request(
                "GET", f"{endpoint.url}{path}", params=params, headers=headers
            )
            try:
                response = await self.client.send(request, stream=True)
            except httpx.HTTPError as exc:
                last_error = exc
                if self.pool is not None:
                    self.pool.mark_down(self.service_code, endpoint.server_id)
                continue
            if response.status_code >= 500 and index < len(candidates) - 1:
                await response.aclose()
                last_error = UpstreamError(
                    "Media service is unavailable",
                    details=f"{endpoint.url}: HTTP {response.status_code}",
                )
                if self.pool is not None:
                    self.pool.mark_down(self.service_code, endpoint.server_id)
                continue
            return response
        raise UpstreamError("Media service is unavailable", details=str(last_error))

    async def close(self) -> None:
        await self.client.aclose()


class CatalogClient(InternalClient):
    service_code = "catalog"
    async def sources(self) -> list[SourceOut]:
        data = await self.request("GET", "/internal/sources")
        return [SourceOut.model_validate(item) for item in data]

    async def manga_list(self, params: dict[str, Any]) -> MangaListResponse:
        data = await self.request("GET", "/internal/manga", params=params)
        return MangaListResponse.model_validate(data)

    async def home_updates(self, limit: int = 25) -> HomeUpdatesOut:
        data = await self.request(
            "GET", "/internal/home/updates", params={"limit": max(1, min(50, limit))}
        )
        return HomeUpdatesOut.model_validate(data)

    async def search(
        self, q: str, *, source: str | None = None, page: int = 1, limit: int = 24
    ) -> MangaListResponse:
        params: dict[str, Any] = {"q": q, "page": page, "limit": limit}
        if source:
            params["source"] = source
        data = await self.request("GET", "/internal/manga/search", params=params)
        return MangaListResponse.model_validate(data)

    async def manga(self, manga_id: str) -> MangaDetailOut:
        data = await self.request("GET", f"/internal/manga/{manga_id}")
        return MangaDetailOut.model_validate(data)

    async def variants(self, manga_id: str) -> MangaVariantsOut:
        data = await self.request("GET", f"/internal/manga/{manga_id}/variants")
        return MangaVariantsOut.model_validate(data)

    async def chapters(
        self, manga_id: str, *, page: int = 1, limit: int = 200, query: str | None = None
    ) -> list[ChapterOut]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if query:
            params["query"] = query
        data = await self.request("GET", f"/internal/manga/{manga_id}/chapters", params=params)
        return [ChapterOut.model_validate(item) for item in data]

    async def import_manga(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/internal/manga/import",
            json={"source": source, "source_id": source_id, "url": url},
        )

    async def import_summary(self, summary: MangaSummary) -> MangaOut:
        data = await self.request(
            "POST", "/internal/manga/import-summary", json=summary.model_dump(mode="json")
        )
        return MangaOut.model_validate(data)

    async def chapter(self, chapter_id: str, *, refresh: bool = True) -> ChapterDetailOut:
        data = await self.request(
            "GET", f"/internal/chapters/{chapter_id}", params={"refresh": refresh}
        )
        return ChapterDetailOut.model_validate(data)

    async def chapter_meta(self, chapter_id: str) -> ChapterOut:
        data = await self.request("GET", f"/internal/chapters/{chapter_id}/meta")
        return ChapterOut.model_validate(data)

    async def stats(self) -> dict[str, Any]:
        return await self.request("GET", "/internal/stats")

    async def enrichment_stats(self) -> dict[str, Any]:
        return await self.request("GET", "/internal/enrichment/stats")

    async def crawl_states(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/internal/crawl-state")
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


class ParserClient(InternalClient):
    service_code = "parser"
    async def sources(self) -> list[SourceInfo]:
        data = await self.request("GET", "/internal/sources")
        return [SourceInfo.model_validate(item) for item in data]

    async def search(self, source: str, q: str, page: int = 1) -> dict[str, Any]:
        return await self.request(
            "GET", "/internal/search", params={"source": source, "q": q, "page": page}
        )

    async def manga(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/internal/manga",
            params={"source": source, "source_id": source_id, "url": url},
        )

    async def chapter(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/internal/chapter",
            params={"source": source, "source_id": source_id, "url": url},
        )


class LibraryClient(InternalClient):
    service_code = "library"
    async def _auth(
        self, method: str, path: str, authorization: str | None, **kwargs: Any
    ) -> Any:
        headers = {"Authorization": authorization} if authorization else {}
        return await self.request(method, path, headers=headers, **kwargs)

    async def register(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> TokenPair:
        data = await self.request("POST", "/internal/auth/register", json=payload, headers=headers)
        return TokenPair.model_validate(data)

    async def login(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> TokenPair:
        data = await self.request("POST", "/internal/auth/login", json=payload, headers=headers)
        return TokenPair.model_validate(data)

    async def refresh(self, refresh_token: str) -> TokenPair:
        data = await self.request(
            "POST", "/internal/auth/refresh", json={"refresh_token": refresh_token}
        )
        return TokenPair.model_validate(data)

    async def logout(self, refresh_token: str) -> None:
        await self.request(
            "POST", "/internal/auth/logout", json={"refresh_token": refresh_token}
        )

    async def me(self, authorization: str) -> UserOut:
        data = await self._auth("GET", "/internal/auth/me", authorization)
        return UserOut.model_validate(data)

    async def bookmarks(self, authorization: str) -> list[BookmarkOut]:
        data = await self._auth("GET", "/internal/me/bookmarks", authorization)
        return [BookmarkOut.model_validate(item) for item in data]

    async def add_bookmark(self, authorization: str, manga_id: str) -> BookmarkOut:
        data = await self._auth(
            "POST", "/internal/me/bookmarks", authorization, json={"manga_id": manga_id}
        )
        return BookmarkOut.model_validate(data)

    async def remove_bookmark(self, authorization: str, manga_id: str) -> None:
        await self._auth("DELETE", f"/internal/me/bookmarks/{manga_id}", authorization)

    async def history(self, authorization: str, limit: int = 100) -> list[ProgressOut]:
        data = await self._auth(
            "GET", "/internal/me/history", authorization, params={"limit": limit}
        )
        return [ProgressOut.model_validate(item) for item in data]

    async def progress(self, authorization: str, limit: int = 100) -> list[ProgressOut]:
        data = await self._auth(
            "GET", "/internal/me/progress", authorization, params={"limit": limit}
        )
        return [ProgressOut.model_validate(item) for item in data]

    async def upsert_progress(
        self, authorization: str, payload: dict[str, Any]
    ) -> ProgressOut:
        data = await self._auth("PUT", "/internal/me/progress", authorization, json=payload)
        return ProgressOut.model_validate(data)

    async def delete_progress(self, authorization: str, manga_id: str) -> None:
        await self._auth("DELETE", f"/internal/me/progress/{manga_id}", authorization)

    async def settings(self, authorization: str) -> ReaderSettings:
        data = await self._auth("GET", "/internal/me/settings", authorization)
        return ReaderSettings.model_validate(data)

    async def save_settings(
        self, authorization: str, payload: ReaderSettings
    ) -> ReaderSettings:
        data = await self._auth(
            "PUT", "/internal/me/settings", authorization, json=payload.model_dump()
        )
        return ReaderSettings.model_validate(data)


class ControlClient(InternalClient):
    service_code = "control"
    async def servers(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/internal/servers")

    async def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/internal/servers", json=payload)

    async def update_server(self, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/internal/servers/{server_id}", json=payload)

    async def delete_server(self, server_id: str) -> None:
        await self.request("DELETE", f"/internal/servers/{server_id}")

    async def deploy(self, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "POST", f"/internal/servers/{server_id}/deploy", json=payload, timeout=30.0
        )

    async def job(self, job_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/internal/jobs/{job_id}")

    async def server_health(self, server_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/internal/servers/{server_id}/health")

    async def promote_replica(self, server_id: str) -> dict[str, Any]:
        return await self.request(
            "POST", f"/internal/servers/{server_id}/replica/promote", timeout=300.0
        )

    async def bootstrap_replica(self, server_id: str, source_server_id: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/internal/servers/{server_id}/replica/bootstrap",
            json={"source_server_id": source_server_id},
            timeout=600.0,
        )

    async def registry(self) -> dict[str, Any]:
        return await self.request("GET", "/internal/registry")

    async def refresh_registry(self) -> dict[str, Any]:
        return await self.request("POST", "/internal/registry/refresh")

    async def select(self, service: str) -> dict[str, Any]:
        return await self.request(
            "POST", "/internal/registry/select", json={"service": service}
        )

    async def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.request("GET", "/internal/audit", params={"limit": limit})


class MediaClient(InternalClient):
    service_code = "media"

    async def archive_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/internal/archives/chapters", json=payload, timeout=30.0)

    async def archive_summary(self, chapter_ids: list[str]) -> list[dict[str, Any]]:
        """Batch archive status; the media query string stays within proxy limits."""

        items: list[dict[str, Any]] = []
        chunk_size = 150
        for index in range(0, len(chapter_ids), chunk_size):
            chunk = chapter_ids[index : index + chunk_size]
            data = await self.request(
                "GET",
                "/internal/archives/chapters/summary",
                params={"ids": ",".join(chunk)},
            )
            chunk_items = data.get("items") if isinstance(data, dict) else None
            if isinstance(chunk_items, list):
                items.extend(item for item in chunk_items if isinstance(item, dict))
        return items

    async def archived_page(self, chapter_id: str, number: int) -> httpx.Response:
        return await self.stream(f"/internal/archives/chapters/{chapter_id}/pages/{number}")

    async def create_export(self, payload: dict[str, Any]) -> ExportJobOut:
        data = await self.request("POST", "/internal/exports", json=payload, timeout=30.0)
        return ExportJobOut.model_validate(data)

    async def export(self, job_id: str) -> ExportJobOut:
        data = await self.request("GET", f"/internal/exports/{job_id}")
        return ExportJobOut.model_validate(data)

    async def delete_export(self, job_id: str) -> None:
        await self.request("DELETE", f"/internal/exports/{job_id}")

    async def download(self, job_id: str) -> httpx.Response:
        return await self.stream(f"/internal/exports/{job_id}/download")

    async def image(self, url: str, referer: str | None = None) -> httpx.Response:
        params = {"url": url}
        if referer:
            params["referer"] = referer
        return await self.stream("/internal/image", params=params)
