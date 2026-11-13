from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
from manga_common.profile_schemas import (
    AdminProfileReportOut,
    MyProfileOut,
    ProfileEventOut,
    ProfileReportOut,
    ProfileUpdate,
    PublicProfileOut,
)
from manga_common.schemas import (
    AnalyticsIngestOut,
    AnalyticsRetentionOut,
    AnalyticsSurfacesOut,
    BookmarkOut,
    ChapterDetailOut,
    ChapterOut,
    CollectionAuditOut,
    CollectionListOut,
    CollectionOut,
    ExportJobOut,
    HomeUpdatesOut,
    MangaDetailOut,
    MangaListResponse,
    MangaOut,
    MangaVariantsOut,
    ProgressMergeOut,
    ProgressOut,
    ReaderSettings,
    RecommendationListOut,
    RelatedMangaOut,
    SitemapEntryOut,
    SourceOut,
    StreakOut,
    SuggestResponse,
    TokenPair,
    TrafficSummaryOut,
    UserOut,
    YandexCallbackOut,
    YandexCredentialsOut,
    YandexDenyOut,
    YandexIntegrationOut,
    YandexIntegrationTestOut,
    YandexIntegrationUpdate,
    YandexStartOut,
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

    async def sitemap_entries(self, *, limit: int = 50_000) -> list[SitemapEntryOut]:
        data = await self.request("GET", "/internal/sitemap", params={"limit": limit})
        return [SitemapEntryOut.model_validate(item) for item in data]

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

    async def suggest(self, q: str, *, limit: int = 6) -> SuggestResponse:
        params: dict[str, Any] = {"q": q, "limit": limit}
        data = await self.request("GET", "/internal/manga/suggest", params=params)
        return SuggestResponse.model_validate(data)

    async def manga(self, manga_id: str) -> MangaDetailOut:
        data = await self.request("GET", f"/internal/manga/{manga_id}")
        return MangaDetailOut.model_validate(data)

    async def variants(self, manga_id: str) -> MangaVariantsOut:
        data = await self.request("GET", f"/internal/manga/{manga_id}/variants")
        return MangaVariantsOut.model_validate(data)

    async def recommendations(self, payload: dict[str, Any]) -> RecommendationListOut:
        data = await self.request("POST", "/internal/recommendations", json=payload)
        return RecommendationListOut.model_validate(data)

    async def related(
        self,
        manga_id: str,
        *,
        history_ids: list[str] | None = None,
        limit: int = 12,
    ) -> RelatedMangaOut:
        params: dict[str, Any] = {"limit": max(6, min(limit, 12))}
        if history_ids:
            params["history"] = ",".join(history_ids[:100])
        data = await self.request(
            "GET", f"/internal/manga/{manga_id}/related", params=params
        )
        return RelatedMangaOut.model_validate(data)

    async def collections(self, *, limit: int = 12) -> CollectionListOut:
        data = await self.request(
            "GET", "/internal/collections", params={"limit": max(1, min(limit, 24))}
        )
        return CollectionListOut.model_validate(data)

    async def collection(self, slug: str, *, limit: int = 24) -> CollectionOut:
        data = await self.request(
            "GET",
            f"/internal/collections/{quote(slug, safe='')}",
            params={"limit": max(1, min(limit, 60))},
        )
        return CollectionOut.model_validate(data)

    async def admin_collections(self) -> CollectionListOut:
        data = await self.request("GET", "/internal/admin/collections")
        return CollectionListOut.model_validate(data)

    async def create_collection(self, payload: dict[str, Any]) -> CollectionOut:
        data = await self.request("POST", "/internal/admin/collections", json=payload)
        return CollectionOut.model_validate(data)

    async def update_collection(
        self, collection_id: str, payload: dict[str, Any]
    ) -> CollectionOut:
        data = await self.request(
            "PATCH", f"/internal/admin/collections/{collection_id}", json=payload
        )
        return CollectionOut.model_validate(data)

    async def delete_collection(self, collection_id: str) -> None:
        await self.request("DELETE", f"/internal/admin/collections/{collection_id}")

    async def add_collection_item(
        self, collection_id: str, manga_id: str
    ) -> CollectionOut:
        data = await self.request(
            "POST",
            f"/internal/admin/collections/{collection_id}/items",
            json={"manga_id": manga_id},
        )
        return CollectionOut.model_validate(data)

    async def remove_collection_item(
        self, collection_id: str, manga_id: str
    ) -> CollectionOut:
        data = await self.request(
            "DELETE", f"/internal/admin/collections/{collection_id}/items/{manga_id}"
        )
        return CollectionOut.model_validate(data)

    async def reorder_collection(
        self, collection_id: str, manga_ids: list[str]
    ) -> CollectionOut:
        data = await self.request(
            "PUT",
            f"/internal/admin/collections/{collection_id}/order",
            json={"manga_ids": manga_ids},
        )
        return CollectionOut.model_validate(data)

    async def collection_audit(self, limit: int = 100) -> list[CollectionAuditOut]:
        data = await self.request(
            "GET", "/internal/admin/collections/audit", params={"limit": limit}
        )
        return [CollectionAuditOut.model_validate(item) for item in data]

    async def link_relations(self, manga_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PUT", f"/internal/manga/{manga_id}/relations", json=payload)

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

    async def yandex_status(self) -> bool:
        data = await self.request("GET", "/internal/auth/yandex/status")
        return bool(data.get("enabled")) if isinstance(data, dict) else False

    async def yandex_start(self, payload: dict[str, Any]) -> YandexStartOut:
        data = await self.request("POST", "/internal/auth/yandex/start", json=payload)
        return YandexStartOut.model_validate(data)

    async def yandex_callback(self, payload: dict[str, Any]) -> YandexCallbackOut:
        data = await self.request("POST", "/internal/auth/yandex/callback", json=payload)
        return YandexCallbackOut.model_validate(data)

    async def yandex_deny(self, payload: dict[str, Any]) -> YandexDenyOut:
        data = await self.request("POST", "/internal/auth/yandex/deny", json=payload)
        return YandexDenyOut.model_validate(data)

    async def yandex_exchange(self, code: str) -> TokenPair:
        data = await self.request(
            "POST", "/internal/auth/yandex/exchange", json={"code": code}
        )
        return TokenPair.model_validate(data)

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

    async def merge_progress(
        self, authorization: str, payload: dict[str, Any]
    ) -> ProgressMergeOut:
        data = await self._auth(
            "POST", "/internal/me/progress/merge", authorization, json=payload
        )
        return ProgressMergeOut.model_validate(data)

    async def streak(self, authorization: str, timezone: str | None) -> StreakOut:
        params = {"timezone": timezone} if timezone else None
        data = await self._auth(
            "GET", "/internal/me/streak", authorization, params=params
        )
        return StreakOut.model_validate(data)

    async def ingest_analytics(self, payload: dict[str, Any]) -> AnalyticsIngestOut:
        data = await self.request("POST", "/internal/analytics/events", json=payload)
        return AnalyticsIngestOut.model_validate(data)

    async def analytics_retention(self, days: int) -> AnalyticsRetentionOut:
        data = await self.request(
            "GET", "/internal/analytics/retention", params={"days": days}
        )
        return AnalyticsRetentionOut.model_validate(data)

    async def profile(
        self,
        handle: str,
        *,
        viewer_id: str | None = None,
        timezone: str | None = None,
    ) -> PublicProfileOut:
        headers = {"X-Viewer-Id": viewer_id} if viewer_id else None
        params = {"timezone": timezone} if timezone else None
        data = await self.request(
            "GET",
            f"/internal/profiles/{quote(handle, safe='')}",
            params=params,
            headers=headers,
        )
        return PublicProfileOut.model_validate(data)

    async def my_profile(
        self, authorization: str, timezone: str | None = None
    ) -> MyProfileOut:
        params = {"timezone": timezone} if timezone else None
        data = await self._auth("GET", "/internal/me/profile", authorization, params=params)
        return MyProfileOut.model_validate(data)

    async def update_profile(
        self, authorization: str, payload: ProfileUpdate
    ) -> MyProfileOut:
        data = await self._auth(
            "PATCH",
            "/internal/me/profile",
            authorization,
            json=payload.model_dump(exclude_unset=True, mode="json"),
        )
        return MyProfileOut.model_validate(data)

    async def my_events(
        self, authorization: str, limit: int = 30
    ) -> list[ProfileEventOut]:
        data = await self._auth(
            "GET",
            "/internal/me/events",
            authorization,
            params={"limit": limit},
        )
        return [ProfileEventOut.model_validate(item) for item in data]

    async def report_profile(
        self, authorization: str, handle: str, reason: str
    ) -> ProfileReportOut:
        data = await self._auth(
            "POST",
            f"/internal/profiles/{quote(handle, safe='')}/reports",
            authorization,
            json={"reason": reason},
        )
        return ProfileReportOut.model_validate(data)

    async def block_profile(
        self, authorization: str, handle: str, *, blocked: bool
    ) -> None:
        method = "POST" if blocked else "DELETE"
        await self._auth(
            method,
            f"/internal/profiles/{quote(handle, safe='')}/block",
            authorization,
        )

    async def admin_profile_reports(
        self, authorization: str, *, status: str = "open", limit: int = 50
    ) -> list[AdminProfileReportOut]:
        data = await self._auth(
            "GET",
            "/internal/admin/profile-reports",
            authorization,
            params={"status": status, "limit": limit},
        )
        return [AdminProfileReportOut.model_validate(item) for item in data]

    async def resolve_profile_report(
        self, authorization: str, report_id: str, status: str
    ) -> AdminProfileReportOut:
        data = await self._auth(
            "PATCH",
            f"/internal/admin/profile-reports/{quote(report_id, safe='')}",
            authorization,
            json={"status": status},
        )
        return AdminProfileReportOut.model_validate(data)
    async def analytics_surfaces(self, days: int) -> AnalyticsSurfacesOut:
        data = await self.request(
            "GET", "/internal/analytics/surfaces", params={"days": days}
        )
        return AnalyticsSurfacesOut.model_validate(data)

    async def record_traffic_visit(self, visitor_hash: str, path_group: str) -> bool:
        data = await self.request(
            "POST",
            "/internal/traffic/visits",
            json={"visitor_hash": visitor_hash, "path_group": path_group},
            timeout=10.0,
        )
        return bool(data.get("recorded")) if isinstance(data, dict) else False

    async def traffic_summary(self) -> TrafficSummaryOut:
        data = await self.request("GET", "/internal/traffic/summary")
        return TrafficSummaryOut.model_validate(data)


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

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/internal/jobs/{job_id}/cancel")

    async def server_health(self, server_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/internal/servers/{server_id}/health")

    async def console(
        self, server_id: str, payload: dict[str, Any], *, admin: str
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/internal/servers/{server_id}/console",
            json=payload,
            headers={"X-Admin-User": admin[:64]},
            timeout=60.0,
        )

    async def console_history(
        self, server_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET",
            f"/internal/servers/{server_id}/console/history",
            params={"limit": limit},
        )

    async def jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.request("GET", "/internal/jobs", params={"limit": limit})

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

    async def yandex_integration(self) -> YandexIntegrationOut:
        data = await self.request("GET", "/internal/integrations/yandex")
        return YandexIntegrationOut.model_validate(data)

    async def update_yandex_integration(
        self, payload: YandexIntegrationUpdate
    ) -> YandexIntegrationOut:
        data = await self.request(
            "PUT",
            "/internal/integrations/yandex",
            json=payload.model_dump(exclude_unset=True),
        )
        return YandexIntegrationOut.model_validate(data)

    async def delete_yandex_integration(self) -> None:
        await self.request("DELETE", "/internal/integrations/yandex")

    async def test_yandex_integration(self) -> YandexIntegrationTestOut:
        data = await self.request("POST", "/internal/integrations/yandex/test")
        return YandexIntegrationTestOut.model_validate(data)

    async def yandex_credentials(self) -> YandexCredentialsOut:
        data = await self.request("GET", "/internal/integrations/yandex/credentials")
        return YandexCredentialsOut.model_validate(data)

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

    async def ads(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/internal/ads")

    async def create_ad(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/internal/ads", json=payload)

    async def update_ad(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "PATCH", f"/internal/ads/{provider_id}", json=payload
        )

    async def delete_ad(self, provider_id: str) -> None:
        await self.request("DELETE", f"/internal/ads/{provider_id}")

    async def set_ad_secret(
        self, provider_id: str, name: str, value: str
    ) -> dict[str, Any]:
        return await self.request(
            "PUT",
            f"/internal/ads/{provider_id}/secrets/{quote(name, safe='')}",
            json={"value": value},
        )

    async def delete_ad_secret(self, provider_id: str, name: str) -> None:
        await self.request(
            "DELETE", f"/internal/ads/{provider_id}/secrets/{quote(name, safe='')}"
        )

    async def ads_public(
        self, *, audience: str, donor: bool, adult: bool, consent: bool
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET",
            "/internal/ads/config",
            params={
                "audience": audience,
                "donor": str(donor).lower(),
                "adult": str(adult).lower(),
                "consent": str(consent).lower(),
            },
        )


class MediaClient(InternalClient):
    service_code = "media"

    async def stats(self) -> dict[str, Any]:
        return await self.request("GET", "/internal/stats")

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
