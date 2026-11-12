from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from manga_common.config import get_settings
from services.notifier.app.config import NotifierSettings
from services.notifier.app.main import create_app

TOKEN = "test-internal-token"


class FakeHTTP:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, json=None, timeout=None):  # type: ignore[no-untyped-def]
        self.calls.append(json or {})
        return SimpleNamespace(status_code=200, text="ok")

    async def aclose(self) -> None:
        return None


def _app(tmp_path, **overrides):  # type: ignore[no-untyped-def]
    settings = NotifierSettings(
        _env_file=None,  # type: ignore[call-arg]
        service_name="notifier-test",
        environment="test",
        log_level="WARNING",
        log_json=False,
        notifier_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'notifier.db').as_posix()}",
        internal_token=TOKEN,
        telegram_bot_token="123:bot-secret-token",
        telegram_chat_id="main-chat",
        **overrides,
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def test_alert_endpoint_uses_dedicated_chat(tmp_path) -> None:
    app = _app(tmp_path, alert_chat_id="alerts-chat")
    fake = FakeHTTP()
    with TestClient(app) as client:
        app.state.http = fake
        response = client.post(
            "/internal/notify/alert",
            headers={"X-Internal-Token": TOKEN},
            json={"text": "disk 95%", "parse_mode": None},
        )

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert fake.calls[0]["chat_id"] == "alerts-chat"
    assert "bot-secret-token" not in response.text


def test_alert_endpoint_falls_back_to_main_chat(tmp_path) -> None:
    app = _app(tmp_path)
    fake = FakeHTTP()
    with TestClient(app) as client:
        app.state.http = fake
        response = client.post(
            "/internal/notify/alert",
            headers={"X-Internal-Token": TOKEN},
            json={"text": "backup stale", "parse_mode": None},
        )

    assert response.status_code == 200
    assert fake.calls[0]["chat_id"] == "main-chat"


def test_alert_endpoint_requires_internal_token(tmp_path) -> None:
    app = _app(tmp_path, alert_chat_id="alerts-chat")
    fake = FakeHTTP()
    with TestClient(app) as client:
        app.state.http = fake
        response = client.post("/internal/notify/alert", json={"text": "x"})

    assert response.status_code == 401
    assert fake.calls == []
