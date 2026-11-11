from __future__ import annotations

import hashlib
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Per-request identity.  The middleware sets it from the mp_client cookie (or a
# stable hash of IP + User-Agent for clients that do not keep cookies).
_client_key: ContextVar[str] = ContextVar("mp_client_key", default="")


def current_client_key() -> str:
    return _client_key.get()


def set_client_key(value: str):
    return _client_key.set(value)


def reset_client_key(token) -> None:  # type: ignore[no-untyped-def]
    _client_key.reset(token)


@dataclass(slots=True)
class Endpoint:
    server_id: str
    server_name: str
    url: str
    priority: int = 100
    is_fallback: bool = False
    is_jump: bool = False
    healthy: bool = False


@dataclass(slots=True)
class _DownMark:
    until: float


def _weighted_score(client_key: str, endpoint: Endpoint) -> int:
    """Rendezvous hash with a priority weight.

    Lower priority numbers should receive more clients.  Dividing the hash by
    ``priority + 1`` keeps the distribution deterministic per client while
    giving the preferred node a larger share.
    """

    digest = hashlib.blake2b(
        f"{client_key}\0{endpoint.server_id}".encode(), digest_size=8
    ).digest()
    value = int.from_bytes(digest, "big")
    return value // max(endpoint.priority, 0) if endpoint.priority > 0 else value


class EndpointPool:
    """Healthy service endpoints plus per-client selection and failover."""

    def __init__(self) -> None:
        self._services: dict[str, list[Endpoint]] = {}
        self._down: dict[tuple[str, str], _DownMark] = {}

    def update(self, registry: dict[str, Any]) -> dict[str, str]:
        services: dict[str, list[Endpoint]] = {}
        for code, items in (registry.get("services") or {}).items():
            parsed: list[Endpoint] = []
            for item in items or []:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                parsed.append(
                    Endpoint(
                        server_id=str(item.get("server_id") or ""),
                        server_name=str(item.get("server_name") or ""),
                        url=str(item["url"]).rstrip("/"),
                        priority=int(item.get("priority") or 100),
                        is_fallback=bool(item.get("is_fallback")),
                        is_jump=bool(item.get("is_jump")),
                        healthy=bool(item.get("healthy")),
                    )
                )
            if parsed:
                services[code] = parsed
        self._services = services
        return {code: items[0].url for code, items in services.items() if items}

    def mark_down(self, service: str, server_id: str, seconds: float = 20.0) -> None:
        if server_id:
            self._down[(service, server_id)] = _DownMark(until=time.monotonic() + seconds)

    def _available(self, service: str) -> list[Endpoint]:
        now = time.monotonic()
        result: list[Endpoint] = []
        for endpoint in self._services.get(service, []):
            if not endpoint.healthy:
                continue
            mark = self._down.get((service, endpoint.server_id))
            if mark is not None and mark.until > now:
                continue
            result.append(endpoint)
        return result

    def choose(
        self, service: str, client_key: str = "", method: str = "GET"
    ) -> list[Endpoint]:
        """Return an ordered list of endpoints to try.

        Writes and stateful reads (library, control) always go to the leader.
        Stateless GETs are spread across healthy nodes with rendezvous hashing,
        giving each client a stable preferred node and a failover list.
        """

        available = self._available(service)
        if not available:
            return []

        if method.upper() != "GET" or service in {"library", "control"}:
            return available[:3]

        preferred = [item for item in available if not item.is_fallback] or available
        key = client_key or "-"
        ordered = sorted(
            preferred,
            key=lambda item: (_weighted_score(key, item), item.url),
            reverse=True,
        )
        # Fallbacks are used only when no preferred node is healthy/available;
        # a failed preferred node is marked down by InternalClient and the next
        # request naturally falls through to this list.
        return ordered[:3]

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            code: [
                {
                    "server_id": item.server_id,
                    "server_name": item.server_name,
                    "url": item.url,
                    "priority": item.priority,
                    "is_fallback": item.is_fallback,
                    "healthy": item.healthy,
                }
                for item in items
            ]
            for code, items in self._services.items()
        }
