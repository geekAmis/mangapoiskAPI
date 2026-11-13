from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mangapoisk_watchdog", ROOT / "scripts" / "ops" / "mangapoisk-watchdog.py"
)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = watchdog
SPEC.loader.exec_module(watchdog)


def test_backup_snapshot_missing_and_present(tmp_path) -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    missing = watchdog.backup_snapshot(tmp_path / "missing.json", required=True, now=now)
    assert missing["configured"] is True
    assert missing["status"] == "missing"
    assert missing["age_seconds"] is None

    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "status": "ok",
                "last_success_at": (now - timedelta(hours=3)).isoformat(),
                "last_attempt_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    present = watchdog.backup_snapshot(path, required=True, now=now)
    assert present["configured"] is True
    assert present["status"] == "ok"
    assert present["age_seconds"] == 3 * 3600


def test_backup_snapshot_falls_back_to_file_mtime_without_success(tmp_path) -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    old = (now - timedelta(hours=27)).timestamp()
    os.utime(path, (old, old))

    snapshot = watchdog.backup_snapshot(path, required=True, now=now)
    assert snapshot["age_seconds"] is not None
    assert snapshot["age_seconds"] >= 26 * 3600


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False

    def read(self) -> bytes:
        return self.body


def _settings(tmp_path) -> object:
    return watchdog.WatchdogSettings(
        gateway_metrics_url="http://127.0.0.1:8100/metrics?format=json",
        notifier_url="http://127.0.0.1:8106",
        notify_path="/internal/notify/alert",
        internal_token="test-internal-token",
        metrics_token=None,
        state_file=tmp_path / "state.json",
        backup_status_file=tmp_path / "status.json",
        backup_required=True,
        disk_path="/",
        cooldown_seconds=3600,
        request_timeout=1,
        dry_run=False,
    )


def test_send_alert_treats_notifier_sent_false_as_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        watchdog.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(b'{"sent": false}'),
    )
    alert = watchdog.Alert(key="disk_usage", severity="critical", summary="disk 95%")
    assert watchdog.send_alert(_settings(tmp_path), alert) is False


def test_send_alert_accepts_sent_true(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        watchdog.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(b'{"sent": true}'),
    )
    alert = watchdog.Alert(key="disk_usage", severity="critical", summary="disk 95%")
    assert watchdog.send_alert(_settings(tmp_path), alert) is True


def test_service_failed_does_not_recover_other_alerts(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(watchdog, "send_alert", lambda *args, **kwargs: True)
    dedupe = watchdog.AlertDeduplicator(cooldown_seconds=3600)
    existing = watchdog.Alert(
        key="service_down:catalog", severity="critical", summary="catalog down"
    )
    assert dedupe.select([existing], now=1000) == [existing]
    watchdog.save_state(settings.state_file, dedupe)

    assert watchdog.run_service_failed(settings, "mangapoisk-gateway.service") == 0

    restored = watchdog.load_state(settings.state_file, cooldown_seconds=3600)
    assert "service_down:catalog" in restored.entries
    assert "service_failed:mangapoisk-gateway.service" in restored.entries


def test_backup_snapshot_failed_status_is_preserved(tmp_path) -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "status": "failed",
                "last_success_at": (now - timedelta(hours=2)).isoformat(),
                "last_error": "restic failed",
            }
        ),
        encoding="utf-8",
    )
    snapshot = watchdog.backup_snapshot(path, required=True, now=now)
    assert snapshot["status"] == "failed"
    assert snapshot["last_error"] == "restic failed"
    assert snapshot["age_seconds"] == 2 * 3600
