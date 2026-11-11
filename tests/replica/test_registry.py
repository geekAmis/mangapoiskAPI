from __future__ import annotations

from typing import Any

import pytest
from services.replica.app.registry import (
    select_replica_target,
    select_targets,
    urls_match,
)


def _endpoint(
    server_id: str,
    url: str,
    *,
    healthy: bool = True,
    fallback: bool = False,
) -> dict[str, Any]:
    return {
        "server_id": server_id,
        "server_name": f"server-{server_id}",
        "host": "127.0.0.1",
        "port": 8000,
        "url": url,
        "healthy": healthy,
        "priority": 10,
        "is_fallback": fallback,
    }


def test_registry_selects_first_healthy_non_fallback_writer() -> None:
    registry = {
        "services": {
            "catalog": [
                _endpoint("unhealthy", "http://unhealthy:8002", healthy=False),
                _endpoint("fallback", "http://fallback:8002", fallback=True),
                _endpoint("primary", "http://primary:8002"),
                _endpoint("secondary", "http://secondary:8002"),
            ],
            "replica": [
                _endpoint("unhealthy", "http://unhealthy:8108"),
                _endpoint("fallback", "http://fallback:8108"),
                _endpoint("primary", "http://primary:8108"),
                _endpoint("secondary", "http://secondary:8108"),
            ],
        }
    }

    target = select_replica_target(registry, "catalog")

    assert target is not None
    assert target.server_id == "primary"
    assert target.leader_service == "catalog"
    assert target.leader_url == "http://primary:8002"
    assert target.replica_url == "http://primary:8108"


def test_registry_skips_writer_without_replica_and_tries_next() -> None:
    registry = {
        "services": {
            "media": [
                _endpoint("writer-only", "http://writer-only:8004"),
                _endpoint("with-replica", "http://with-replica:8004"),
            ],
            "replica": [
                _endpoint("with-replica", "http://with-replica:8108"),
            ],
        }
    }

    target = select_replica_target(registry, "media")

    assert target is not None
    assert target.server_id == "with-replica"


def test_registry_self_is_skipped() -> None:
    registry = {
        "services": {
            "library": [_endpoint("primary", "http://primary:8003")],
            "replica": [_endpoint("primary", "http://primary:8108/")],
        }
    }

    assert select_replica_target(
        registry, "library", self_url="http://primary:8108"
    ) is None
    assert urls_match("http://primary:8108/", "http://PRIMARY:8108")


def test_registry_no_healthy_writer_returns_none() -> None:
    registry = {
        "services": {
            "control": [
                _endpoint("fallback", "http://fallback:8005", fallback=True),
                _endpoint("down", "http://down:8005", healthy=False),
            ],
            "replica": [
                _endpoint("fallback", "http://fallback:8108"),
                _endpoint("down", "http://down:8108"),
            ],
        }
    }

    assert select_replica_target(registry, "control") is None
    assert select_replica_target({"services": {}}, "control") is None


def test_registry_unknown_store_raises() -> None:
    with pytest.raises(ValueError):
        select_replica_target({"services": {}}, "nope")


def test_select_targets_covers_requested_stores() -> None:
    registry = {
        "services": {
            "catalog": [_endpoint("a", "http://a:8002")],
            "replica": [_endpoint("a", "http://a:8108")],
        }
    }

    targets = select_targets(registry, stores=["catalog", "library"])

    assert targets["catalog"] is not None
    assert targets["library"] is None
