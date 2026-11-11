from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .config import STORE_NAMES

# Each replicated store is written by the corresponding writable service.  The
# replica service that runs on the same server (identified by server_id) is the
# one that can serve us a consistent copy.
LEADER_SERVICE: dict[str, str] = {
    "catalog": "catalog",
    "library": "library",
    "control": "control",
    "media": "media",
}


@dataclass(frozen=True, slots=True)
class ReplicaTarget:
    store: str
    leader_service: str
    server_id: str
    server_name: str
    leader_url: str
    replica_url: str


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def urls_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return normalize_url(left).casefold() == normalize_url(right).casefold()


def _services(registry: Mapping[str, Any], code: str) -> list[Mapping[str, Any]]:
    services = registry.get("services")
    if not isinstance(services, Mapping):
        return []
    items = services.get(code)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def select_replica_target(
    registry: Mapping[str, Any],
    store: str,
    *,
    self_url: str | None = None,
) -> ReplicaTarget | None:
    """Pick the replica endpoint for a store from a registry payload.

    The control registry already orders endpoints by fallback flag, health and
    server age, so the first healthy non-fallback writer wins.  If its replica
    is this node (``self_url``), the store is skipped: we are the source.

    This is a pure function and is covered directly by unit tests.
    """

    if store not in LEADER_SERVICE:
        raise ValueError(f"Unknown replica store: {store}")
    leader_service = LEADER_SERVICE[store]

    replicas: dict[str, Mapping[str, Any]] = {}
    for endpoint in _services(registry, "replica"):
        server_id = endpoint.get("server_id")
        url = endpoint.get("url")
        if server_id is None or not url:
            continue
        replicas[str(server_id)] = endpoint

    for endpoint in _services(registry, leader_service):
        if not endpoint.get("healthy") or endpoint.get("is_fallback"):
            continue
        server_id = endpoint.get("server_id")
        if server_id is None:
            continue
        replica = replicas.get(str(server_id))
        if replica is None:
            continue
        replica_url = normalize_url(str(replica.get("url") or ""))
        if not replica_url:
            continue
        if self_url and urls_match(replica_url, self_url):
            return None
        return ReplicaTarget(
            store=store,
            leader_service=leader_service,
            server_id=str(server_id),
            server_name=str(
                replica.get("server_name")
                or endpoint.get("server_name")
                or endpoint.get("host")
                or server_id
            ),
            leader_url=normalize_url(str(endpoint.get("url") or "")),
            replica_url=replica_url,
        )
    return None


def select_targets(
    registry: Mapping[str, Any],
    *,
    stores: Sequence[str] | None = None,
    self_url: str | None = None,
) -> dict[str, ReplicaTarget | None]:
    selected = stores or STORE_NAMES
    return {
        store: select_replica_target(registry, store, self_url=self_url)
        for store in selected
    }
