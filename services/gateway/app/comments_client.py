from __future__ import annotations

from typing import Any

from .clients import InternalClient


class CommentsClient(InternalClient):
    service_code = "comments"

    async def list_comments(
        self,
        manga_id: str,
        *,
        page: int = 1,
        limit: int = 20,
        sort: str = "new",
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/internal/manga/{manga_id}/comments",
            params={"page": page, "limit": limit, "sort": sort},
            headers=headers,
        )

    async def replies(
        self, comment_id: str, *, page: int = 1, limit: int = 20, headers=None
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/internal/comments/{comment_id}/replies",
            params={"page": page, "limit": limit},
            headers=headers,
        )

    async def create(
        self, manga_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/internal/manga/{manga_id}/comments", json=payload, headers=headers
        )

    async def update(self, comment_id: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        return await self.request(
            "PATCH", f"/internal/comments/{comment_id}", json=payload, headers=headers
        )

    async def delete(self, comment_id: str, headers: dict[str, str]) -> None:
        await self.request("DELETE", f"/internal/comments/{comment_id}", headers=headers)

    async def like(self, comment_id: str, headers: dict[str, str]) -> dict[str, Any]:
        return await self.request("POST", f"/internal/comments/{comment_id}/like", headers=headers)

    async def report(
        self, comment_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/internal/comments/{comment_id}/report", json=payload, headers=headers
        )

    async def notifications(
        self,
        *,
        unread_only: bool = False,
        page: int = 1,
        limit: int = 20,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/internal/notifications",
            params={"unread_only": unread_only, "page": page, "limit": limit},
            headers=headers,
        )

    async def read_notifications(self, ids: list[str], headers: dict[str, str]) -> dict[str, Any]:
        return await self.request(
            "POST", "/internal/notifications/read", json={"ids": ids}, headers=headers
        )

    async def follows(self, headers: dict[str, str]) -> list[dict[str, Any]]:
        return await self.request("GET", "/internal/follows", headers=headers)

    async def follow(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST", "/internal/follows", json=payload, headers=headers
        )

    async def unfollow(self, manga_id: str, headers: dict[str, str]) -> dict[str, Any]:
        return await self.request(
            "DELETE", f"/internal/follows/{manga_id}", headers=headers
        )

    async def follow_status(
        self, manga_id: str, headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/internal/follows/{manga_id}", headers=headers
        )

    async def notification_settings(self, headers: dict[str, str]) -> dict[str, Any]:
        return await self.request(
            "GET", "/internal/notifications/settings", headers=headers
        )

    async def save_notification_settings(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", "/internal/notifications/settings", json=payload, headers=headers
        )

    async def admin_comments(
        self,
        *,
        status: str | None,
        reported: bool | None,
        page: int,
        limit: int,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        if reported is not None:
            params["reported"] = reported
        return await self.request("GET", "/internal/admin/comments", params=params, headers=headers)

    async def admin_moderate(
        self, comment_id: str, action: str, headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/internal/admin/comments/{comment_id}/{action}", headers=headers
        )

    async def admin_reports(
        self,
        *,
        status: str | None,
        page: int,
        limit: int,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        return await self.request("GET", "/internal/admin/reports", params=params, headers=headers)

    async def admin_resolve_report(
        self, report_id: str, status: str, headers: dict[str, str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/internal/admin/reports/{report_id}/resolve",
            json={"status": status},
            headers=headers,
        )
