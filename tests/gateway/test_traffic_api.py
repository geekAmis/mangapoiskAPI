from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import AppError, app_error_handler
from manga_common.schemas import TrafficDayOut, TrafficSummaryOut
from manga_common.security import require_admin
from services.gateway.app import traffic as traffic_module

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
SECRET = "gateway-traffic-test-secret"
VISITOR = "abcdef1234567890"


class FakeLibrary:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def record_traffic_visit(self, visitor_hash: str, path_group: str) -> bool:
        self.calls.append((visitor_hash, path_group))
        return True

    async def traffic_summary(self) -> TrafficSummaryOut:
        return TrafficSummaryOut(
            generated_at=NOW,
            unique_visitors_7d=2,
            unique_visitors_30d=3,
            unique_visitors_today=1,
            weekly_goal=100,
            progress_percent=2.0,
            last_visit_at=NOW,
            retention_days=90,
            daily=[TrafficDayOut(day=date(2026, 11, 13), unique_visitors=1)],
        )


def make_client(*, admin: bool = False) -> tuple[TestClient, FakeLibrary]:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    library = FakeLibrary()
    app.state.library = library
    app.state.settings = SimpleNamespace(traffic_secret=SECRET)
    app.include_router(traffic_module.router)
    if admin:
        app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app), library


def test_visit_hashes_visitor_and_forwards_only_safe_fields() -> None:
    client, library = make_client()
    with client as http:
        response = http.post(
            "/api/v1/traffic/visit",
            json={"visitor_id": VISITOR, "path_group": "manga"},
        )

    assert response.status_code == 200
    assert response.json() == {"recorded": True}
    digest, group = library.calls[0]
    expected = hmac.new(
        SECRET.encode(),
        b"mangapoisk-traffic-v1\x00" + VISITOR.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert digest == expected
    assert VISITOR not in digest
    assert group == "manga"


def test_visit_rejects_pii_fields_and_unknown_groups() -> None:
    client, library = make_client()
    with client as http:
        with_pii = http.post(
            "/api/v1/traffic/visit",
            json={
                "visitor_id": VISITOR,
                "path_group": "home",
                "ip_address": "203.0.113.10",
            },
        )
        bad_group = http.post(
            "/api/v1/traffic/visit",
            json={"visitor_id": VISITOR, "path_group": "admin"},
        )

    assert with_pii.status_code == 422
    assert bad_group.status_code == 422
    assert library.calls == []


def test_visit_ignores_known_bots_without_storing_anything() -> None:
    client, library = make_client()
    with client as http:
        response = http.post(
            "/api/v1/traffic/visit",
            json={"visitor_id": VISITOR, "path_group": "home"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; YandexBot/3.0)"},
        )

    assert response.status_code == 200
    assert response.json() == {"recorded": False}
    assert library.calls == []


def test_admin_traffic_requires_admin_and_returns_aggregates_only() -> None:
    client, _ = make_client()
    with client as http:
        assert http.get("/api/v1/admin/traffic").status_code == 401

    client, _ = make_client(admin=True)
    with client as http:
        response = http.get("/api/v1/admin/traffic")

    assert response.status_code == 200
    payload = response.json()
    assert payload["unique_visitors_7d"] == 2
    assert payload["unique_visitors_30d"] == 3
    assert payload["last_visit_at"] is not None
    assert payload["weekly_goal"] == 100
    assert "visitor_hash" not in payload
    assert SECRET not in response.text
