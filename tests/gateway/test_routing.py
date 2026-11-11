from __future__ import annotations

from services.gateway.app.routing import EndpointPool


def registry() -> dict:
    return {
        "services": {
            "catalog": [
                {
                    "server_id": "primary",
                    "server_name": "primary",
                    "url": "http://primary:8102",
                    "healthy": True,
                    "priority": 10,
                    "is_fallback": False,
                    "is_jump": False,
                },
                {
                    "server_id": "secondary",
                    "server_name": "secondary",
                    "url": "http://secondary:8102",
                    "healthy": True,
                    "priority": 50,
                    "is_fallback": False,
                    "is_jump": False,
                },
                {
                    "server_id": "spare",
                    "server_name": "spare",
                    "url": "http://spare:8102",
                    "healthy": True,
                    "priority": 1,
                    "is_fallback": True,
                    "is_jump": False,
                },
            ],
            "library": [
                {
                    "server_id": "primary",
                    "server_name": "primary",
                    "url": "http://primary:8103",
                    "healthy": True,
                    "priority": 10,
                    "is_fallback": False,
                    "is_jump": False,
                }
            ],
        }
    }


def test_requests_are_per_client_and_stable() -> None:
    pool = EndpointPool()
    pool.update(registry())
    first = pool.choose("catalog", "client-a", "GET")
    second = pool.choose("catalog", "client-a", "GET")
    assert [item.server_id for item in first] == [item.server_id for item in second]
    assert first[0].server_id in {"primary", "secondary"}
    assert all(item.server_id != "spare" for item in first)


def test_writes_and_stateful_reads_use_leader() -> None:
    pool = EndpointPool()
    pool.update(registry())
    assert pool.choose("catalog", "client-a", "POST")[0].server_id == "primary"
    assert pool.choose("library", "client-a", "GET")[0].server_id == "primary"


def test_failover_skips_marked_endpoint() -> None:
    pool = EndpointPool()
    pool.update(registry())
    pool.mark_down("catalog", "primary", 60)
    chosen = pool.choose("catalog", "client-a", "GET")
    assert chosen
    assert chosen[0].server_id != "primary"
    assert all(item.server_id != "primary" for item in chosen)


def test_unhealthy_nodes_are_never_chosen() -> None:
    data = registry()
    data["services"]["catalog"][0]["healthy"] = False
    data["services"]["catalog"][1]["healthy"] = False
    pool = EndpointPool()
    pool.update(data)
    chosen = pool.choose("catalog", "client-a", "GET")
    assert [item.server_id for item in chosen] == ["spare"]
