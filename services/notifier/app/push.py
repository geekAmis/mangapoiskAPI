from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any, Protocol
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import NotifierSettings
from .models import PushBatch, PushDelivery, PushSubscription

logger = logging.getLogger(__name__)


class PushDeliveryError(Exception):
    def __init__(self, message: str, *, gone: bool = False) -> None:
        super().__init__(message)
        self.gone = gone


class PushSender(Protocol):
    async def __call__(
        self, subscription: dict[str, Any], payload: dict[str, Any]
    ) -> None: ...


@dataclass(slots=True)
class PushStats:
    configured: bool
    events: int
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    deduped: int = 0
    skipped_events: int = 0
    deliveries: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str, *, batches: int = 1, events: int = 0) -> None:
        self.skipped += batches
        self.skipped_events += events
        self.reasons[reason] = self.reasons.get(reason, 0) + batches

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "events": self.events,
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": self.failed,
            "deduped": self.deduped,
            "skipped_events": self.skipped_events,
            "deliveries": self.deliveries,
            "reasons": self.reasons,
        }


class PywebpushSender:
    """Encrypt payloads with http-ece and sign VAPID using pywebpush."""

    def __init__(self, settings: NotifierSettings) -> None:
        self.settings = settings

    def _vapid(self):  # type: ignore[no-untyped-def]
        from py_vapid import Vapid

        private_key = (self.settings.vapid_private_key or "").strip()
        if not private_key:
            raise PushDeliveryError("VAPID private key is not configured")
        if private_key.startswith("-----BEGIN"):
            return Vapid.from_pem(private_key.encode("utf-8"))
        return Vapid.from_raw(private_key.encode("utf-8"))

    async def __call__(
        self, subscription: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        from pywebpush import WebPushException, webpush

        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription,
                data=data,
                vapid_private_key=self._vapid(),
                vapid_claims={"sub": self.settings.vapid_subject},
                ttl=self.settings.push_ttl_seconds,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise PushDeliveryError(str(exc), gone=status in {404, 410}) from exc
        except Exception as exc:  # pragma: no cover - network/library failures
            raise PushDeliveryError(str(exc)) from exc


Clock = Callable[[], datetime]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def in_quiet_hours(start: int | None, end: int | None, hour: int) -> bool:
    """Return True inside a quiet-hours window (UTC).

    ``start == end`` is treated as "disabled" rather than a full day, so a
    user who drags both selects to the same value does not silently lose every
    push.  Windows crossing midnight are supported (22 -> 8).
    """

    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def build_payload(
    manga_id: str,
    manga_title: str,
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    labels = [str(item.get("chapter_label") or "Новая глава") for item in chapters]
    first = chapters[0]
    url = str(first.get("chapter_url") or "")
    if not url.startswith("/"):
        url = f"/reader/{first.get('chapter_id')}"
    if len(chapters) == 1:
        title = f"Новая глава — {manga_title}"
        body = labels[0]
    else:
        shown = ", ".join(labels[:3])
        if len(labels) > 3:
            shown += f" и ещё {len(labels) - 3}"
        title = f"Новые главы — {manga_title}"
        body = f"{len(labels)} главы: {shown}"
    return {
        "title": title[:120],
        "body": body[:300],
        "tag": f"chapter-{manga_id}",
        "renotify": False,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/favicon.svg",
        "data": {
            "type": "chapter",
            "manga_id": manga_id,
            "chapter_ids": [str(item.get("chapter_id")) for item in chapters],
            "url": url,
        },
    }


class PushService:
    def __init__(
        self,
        settings: NotifierSettings,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        sender: PushSender | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.sender = sender or PywebpushSender(settings)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ config
    @property
    def configured(self) -> bool:
        return bool(
            self.settings.web_push_enabled
            and self.settings.vapid_private_key
            and self.public_key
        )

    @property
    def public_key(self) -> str | None:
        if self.settings.vapid_public_key:
            return self.settings.vapid_public_key.strip()
        private_key = (self.settings.vapid_private_key or "").strip()
        if not private_key:
            return None
        try:
            from cryptography.hazmat.primitives import serialization
            from py_vapid import Vapid, utils

            vapid = (
                Vapid.from_pem(private_key.encode("utf-8"))
                if private_key.startswith("-----BEGIN")
                else Vapid.from_raw(private_key.encode("utf-8"))
            )
            raw = vapid.public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
            return utils.b64urlencode(raw)
        except Exception as exc:  # pragma: no cover - malformed operator key
            logger.warning("could not derive VAPID public key: %s", exc)
            return None

    def config(self) -> dict[str, Any]:
        return {
            "enabled": self.configured,
            "public_key": self.public_key if self.configured else None,
            "reason": None if self.configured else "web_push_not_configured",
        }

    # ---------------------------------------------------------- subscriptions
    def _validate_endpoint(self, endpoint: str) -> str:
        endpoint = (endpoint or "").strip()
        if not endpoint or len(endpoint) > 2048:
            raise ValueError("Некорректный push endpoint")
        parsed = urlparse(endpoint)
        scheme = parsed.scheme.lower()
        if scheme != "https" and not (
            self.settings.push_allow_insecure_endpoints and scheme == "http"
        ):
            raise ValueError("Push endpoint должен использовать HTTPS")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError("Push endpoint без хоста")
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            raise ValueError("Push endpoint указывает на приватный адрес")
        if host in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Push endpoint указывает на локальный адрес")
        allowed = self.settings.allowed_push_hosts
        if allowed and not any(host == item or host.endswith("." + item) for item in allowed):
            raise ValueError("Push endpoint не принадлежит известному push-сервису")
        return endpoint

    async def subscribe(
        self,
        *,
        user_id: uuid.UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        endpoint = self._validate_endpoint(endpoint)
        p256dh = (p256dh or "").strip()
        auth = (auth or "").strip()
        if not p256dh or len(p256dh) > 255 or not auth or len(auth) > 64:
            raise ValueError("Некорректные ключи push-подписки")
        async with self.session_factory() as session:
            subscription = await session.scalar(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            if subscription is None:
                active_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(PushSubscription)
                        .where(
                            PushSubscription.user_id == user_id,
                            PushSubscription.active.is_(True),
                        )
                    )
                    or 0
                )
                if active_count >= self.settings.push_max_subscriptions_per_user:
                    oldest = await session.scalar(
                        select(PushSubscription)
                        .where(
                            PushSubscription.user_id == user_id,
                            PushSubscription.active.is_(True),
                        )
                        .order_by(PushSubscription.created_at.asc())
                        .limit(1)
                    )
                    if oldest is not None:
                        await session.delete(oldest)
                subscription = PushSubscription(
                    user_id=user_id,
                    endpoint=endpoint,
                    p256dh=p256dh,
                    auth=auth,
                    user_agent=(user_agent or "")[:512] or None,
                    active=True,
                )
                session.add(subscription)
            else:
                # A browser subscription belongs to the user who is signed in
                # on that device now: re-assign instead of violating the
                # endpoint unique constraint.
                subscription.user_id = user_id
                subscription.p256dh = p256dh
                subscription.auth = auth
                subscription.user_agent = (user_agent or "")[:512] or None
                subscription.active = True
            await session.commit()
            return {"subscribed": True, "endpoint_host": urlparse(endpoint).hostname}

    async def unsubscribe(self, *, user_id: uuid.UUID, endpoint: str) -> bool:
        async with self.session_factory() as session:
            subscription = await session.scalar(
                select(PushSubscription).where(
                    PushSubscription.user_id == user_id,
                    PushSubscription.endpoint == endpoint,
                )
            )
            if subscription is None:
                return False
            await session.delete(subscription)
            await session.commit()
            return True

    async def status(self, user_id: uuid.UUID) -> dict[str, Any]:
        async with self.session_factory() as session:
            rows = list(
                await session.scalars(
                    select(PushSubscription)
                    .where(
                        PushSubscription.user_id == user_id,
                        PushSubscription.active.is_(True),
                    )
                    .order_by(PushSubscription.created_at.desc())
                )
            )
            return {
                "subscribed": bool(rows),
                "count": len(rows),
                "endpoints": [
                    {
                        "host": urlparse(row.endpoint).hostname,
                        "created_at": _as_utc(row.created_at).isoformat(),
                    }
                    for row in rows
                ],
            }

    # -------------------------------------------------------------- delivery
    async def _count_user_batches(self, session: AsyncSession, user_id: uuid.UUID, since: datetime) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(PushBatch)
                .where(PushBatch.user_id == user_id, PushBatch.created_at >= since)
            )
            or 0
        )

    def _quiet_window(
        self, recipient: dict[str, Any]
    ) -> tuple[int | None, int | None]:
        start = recipient.get("quiet_hours_start")
        end = recipient.get("quiet_hours_end")
        if start is None and end is None:
            start = self.settings.push_quiet_hours_start
            end = self.settings.push_quiet_hours_end
        return start, end

    async def send_chapters(
        self,
        *,
        events: list[dict[str, Any]],
        recipients: list[dict[str, Any]],
    ) -> dict[str, Any]:
        stats = PushStats(configured=self.configured, events=len(events))
        if not events or not recipients:
            return stats.as_dict()
        if not self.configured:
            stats.skipped += len(recipients)
            stats.reasons["not_configured"] = len(recipients)
            return stats.as_dict()

        # Normalise and group recipients; a duplicate user id keeps the most
        # restrictive hourly limit and the last quiet-hours preference.
        normalized: dict[uuid.UUID, dict[str, Any]] = {}
        for raw in recipients:
            try:
                user_id = uuid.UUID(str(raw.get("user_id")))
            except (TypeError, ValueError):
                continue
            normalized[user_id] = raw

        now = self.clock()
        since = now - timedelta(hours=1)
        hour = now.astimezone(UTC).hour

        async with self._lock:
            for user_id, recipient in normalized.items():
                by_title: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
                seen_chapters: set[str] = set()
                for event in events:
                    try:
                        manga_id = uuid.UUID(str(event.get("manga_id")))
                        chapter_key = str(uuid.UUID(str(event.get("chapter_id"))))
                    except (TypeError, ValueError):
                        continue
                    # Duplicate events in one scheduler payload (retry, two
                    # catalogue passes) must not create two delivery rows.
                    dedupe_key = f"{manga_id}:{chapter_key}"
                    if dedupe_key in seen_chapters:
                        continue
                    seen_chapters.add(dedupe_key)
                    by_title[manga_id].append(event)

                for manga_id, title_events in by_title.items():
                    async with self.session_factory() as session:
                        chapter_ids = [
                            uuid.UUID(str(event.get("chapter_id")))
                            for event in title_events
                            if event.get("chapter_id")
                        ]
                        if not chapter_ids:
                            stats.skip("invalid_event", events=len(title_events))
                            continue
                        existing = set(
                            await session.scalars(
                                select(PushDelivery.chapter_id).where(
                                    PushDelivery.user_id == user_id,
                                    PushDelivery.chapter_id.in_(chapter_ids),
                                )
                            )
                        )
                        fresh = [
                            event
                            for event in title_events
                            if uuid.UUID(str(event.get("chapter_id"))) not in existing
                        ]
                        stats.deduped += len(title_events) - len(fresh)
                        if not fresh:
                            stats.skipped += 1
                            continue

                        start, end = self._quiet_window(recipient)
                        if in_quiet_hours(start, end, hour):
                            stats.skip("quiet_hours", events=len(fresh))
                            continue

                        limit = min(
                            int(recipient.get("max_pushes_per_hour") or 5),
                            self.settings.push_max_per_hour,
                        )
                        if await self._count_user_batches(session, user_id, since) >= limit:
                            stats.skip("rate_limited", events=len(fresh))
                            continue

                        subscriptions = list(
                            await session.scalars(
                                select(PushSubscription).where(
                                    PushSubscription.user_id == user_id,
                                    PushSubscription.active.is_(True),
                                )
                            )
                        )
                        if not subscriptions:
                            stats.skip("no_subscription", events=len(fresh))
                            continue

                        chapter_count = len(fresh)
                        payload = build_payload(
                            str(manga_id),
                            str(fresh[0].get("manga_title") or "MangaPoisk Reborn"),
                            fresh,
                        )
                        batch = PushBatch(
                            user_id=user_id,
                            manga_id=manga_id,
                            chapter_count=chapter_count,
                            status="pending",
                        )
                        session.add(batch)
                        await session.flush()
                        deliveries = [
                            PushDelivery(
                                user_id=user_id,
                                manga_id=manga_id,
                                chapter_id=uuid.UUID(str(event.get("chapter_id"))),
                                status="pending",
                            )
                            for event in fresh
                        ]
                        session.add_all(deliveries)
                        await session.commit()

                        sent_any = False
                        errors: list[str] = []
                        for subscription in subscriptions:
                            info = {
                                "endpoint": subscription.endpoint,
                                "keys": {
                                    "p256dh": subscription.p256dh,
                                    "auth": subscription.auth,
                                },
                            }
                            try:
                                await self.sender(info, payload)
                                sent_any = True
                            except PushDeliveryError as exc:
                                errors.append(str(exc))
                                if exc.gone:
                                    subscription.active = False
                            except Exception as exc:  # defensive: sender contract
                                errors.append(str(exc))
                        stats.deliveries += len(subscriptions)
                        status = "sent" if sent_any else "failed"
                        batch.status = status
                        for delivery in deliveries:
                            delivery.status = status
                            delivery.error = None if sent_any else ("; ".join(errors)[:1000] or "push failed")
                        await session.commit()
                        if sent_any:
                            stats.sent += 1
                        else:
                            stats.failed += 1
                            stats.reasons["delivery_failed"] = (
                                stats.reasons.get("delivery_failed", 0) + 1
                            )
        return stats.as_dict()
