from __future__ import annotations

from fastapi.testclient import TestClient
from manga_common.config import Settings
from manga_common.metrics import MetricsRegistry, RollingHTTPMetrics, percentile, reset_metrics
from manga_common.service import create_service_app


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_percentile_nearest_rank() -> None:
    values = [float(value) for value in range(1, 101)]
    assert percentile([], 0.95) == 0.0
    assert percentile(values, 0.50) == 50.0
    assert percentile(values, 0.95) == 95.0
    assert percentile(values, 0.99) == 99.0
    assert percentile([3.0], 0.99) == 3.0


def test_rolling_metrics_aggregate_counts_errors_and_percentiles() -> None:
    clock = FakeClock()
    rolling = RollingHTTPMetrics(clock=clock)
    for index in range(1, 101):
        status = 500 if index <= 5 else 200
        rolling.record("GET", status, index / 1000)

    five = rolling.window(5)
    assert five.requests == 100
    assert five.errors == 5
    assert five.error_rate == 0.05
    assert five.p50_ms == 50.0
    assert five.p95_ms == 95.0
    assert five.p99_ms == 99.0

    clock.advance(6 * 60)
    old = rolling.window(5)
    assert old.requests == 0
    assert old.error_rate == 0.0

    rolling.record("POST", 503, 0.25)
    fresh = rolling.window(5)
    assert fresh.requests == 1
    assert fresh.errors == 1
    assert fresh.error_rate == 1.0


def test_registry_snapshot_exposes_http_and_db_counters() -> None:
    registry = MetricsRegistry(clock=FakeClock(), service="test")
    registry.observe_http("GET", 200, 0.1)
    registry.observe_http("GET", 500, 0.2)
    registry.record_db_lock_error()
    registry.record_db_lock_retry()
    registry.record_db_lock_recovered()
    registry.set("mangapoisk_service_up", 0, service="catalog")

    snapshot = registry.snapshot()
    assert snapshot["service"] == "test"
    assert snapshot["http"]["total"] == 2
    assert snapshot["http"]["errors_5xx"] == 1
    assert snapshot["http"]["error_rate"] == 0.5
    assert snapshot["db"]["errors_total"] == 1
    assert snapshot["db"]["retries_total"] == 1
    assert snapshot["db"]["recovered_total"] == 1
    assert snapshot["db"]["errors_1m"] == 1
    assert any(
        item["name"] == "mangapoisk_service_up" and item["labels"] == {"service": "catalog"}
        for item in snapshot["gauges"]
    )


def test_prometheus_render_has_quantiles_and_escaped_labels() -> None:
    registry = MetricsRegistry(clock=FakeClock(), service="test")
    registry.observe_http("GET", 200, 0.123)
    registry.set("mangapoisk_custom", 1, note='a"b\nc')

    text = registry.render_prometheus()
    assert 'mangapoisk_http_request_duration_seconds{quantile="0.95",window="5m"}' in text
    assert 'mangapoisk_http_5xx_ratio{window="5m"}' in text
    assert 'mangapoisk_custom{note="a\\"b\\nc"} 1' in text


def test_prometheus_families_have_unique_help_and_type_lines() -> None:
    registry = MetricsRegistry(clock=FakeClock(), service="test")
    registry.observe_http("GET", 200, 0.123)
    registry.observe_http("GET", 500, 0.456)
    registry.inc("mangapoisk_custom_counter_total", 3)
    registry.set("mangapoisk_custom_gauge", 2)

    text = registry.render_prometheus()
    type_names = [
        line.split()[2]
        for line in text.splitlines()
        if line.startswith("# TYPE ")
    ]
    assert len(type_names) == len(set(type_names)), "duplicate TYPE lines break scrapes"
    assert type_names.count("mangapoisk_http_5xx_ratio") == 1
    assert type_names.count("mangapoisk_http_request_duration_seconds") == 1
    assert (
        "# TYPE mangapoisk_custom_counter_total counter" in text
    ), "generic counters must be exported as counters"
    assert "# TYPE mangapoisk_custom_gauge gauge" in text
    assert "mangapoisk_custom_counter_total 3.0" in text


def test_prometheus_render_keeps_every_series_in_a_family() -> None:
    registry = MetricsRegistry(clock=FakeClock(), service="test")
    registry.set("mangapoisk_service_up", 1, service="catalog")
    registry.set("mangapoisk_service_up", 0, service="media")
    registry.inc("mangapoisk_worker_jobs_total", 2, queue="enrichment")
    registry.inc("mangapoisk_worker_jobs_total", 3, queue="search")

    text = registry.render_prometheus()
    assert text.count("# TYPE mangapoisk_service_up gauge") == 1
    assert text.count("# TYPE mangapoisk_worker_jobs_total counter") == 1
    assert 'mangapoisk_service_up{service="catalog"} 1.0' in text
    assert 'mangapoisk_service_up{service="media"} 0.0' in text
    assert 'mangapoisk_worker_jobs_total{queue="enrichment"} 2.0' in text
    assert 'mangapoisk_worker_jobs_total{queue="search"} 3.0' in text


def test_metrics_endpoint_supports_prometheus_and_json() -> None:
    reset_metrics()
    app = create_service_app(
        settings=Settings(service_name="metrics-test", environment="test", log_json=False),
        title="metrics test",
        description="metrics test",
    )

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"ok": "yes"}

    with TestClient(app) as client:
        assert client.get("/hello").status_code == 200
        payload = client.get("/metrics?format=json").json()
        assert payload["service"] == "metrics-test"
        assert payload["http"]["windows"]["5m"]["requests"] >= 1
        text = client.get("/metrics").text
        assert "mangapoisk_http_requests_total" in text
        assert "mangapoisk_http_request_duration_seconds" in text


def test_metrics_json_uses_gateway_snapshot_provider() -> None:
    reset_metrics()
    app = create_service_app(
        settings=Settings(service_name="gateway-test", environment="test", log_json=False),
        title="gateway test",
        description="gateway test",
    )
    app.state.metrics_snapshot_provider = lambda: {
        "service": "gateway",
        "http": {"windows": {}},
        "db": {"errors_5m": 7},
        "services": {"catalog": True},
        "alerts": [],
    }

    with TestClient(app) as client:
        payload = client.get("/metrics?format=json").json()
        assert payload["services"] == {"catalog": True}
        assert payload["db"]["errors_5m"] == 7
        # Prometheus text still comes from the local registry.
        assert "mangapoisk_uptime_seconds" in client.get("/metrics").text


def test_metrics_token_protects_endpoint_and_body_has_no_secrets() -> None:
    reset_metrics()
    settings = Settings(
        service_name="metrics-security",
        environment="test",
        log_json=False,
        jwt_secret="jwt-super-secret",
        internal_token="internal-super-secret",
        admin_password="admin-super-secret",
        metrics_token="metrics-super-secret",
    )
    app = create_service_app(settings=settings, title="security", description="security")

    with TestClient(app) as client:
        denied = client.get("/metrics")
        assert denied.status_code == 401
        allowed = client.get("/metrics", headers={"X-Metrics-Token": "metrics-super-secret"})
        assert allowed.status_code == 200

    body = allowed.text
    for secret in (
        "jwt-super-secret",
        "internal-super-secret",
        "admin-super-secret",
        "metrics-super-secret",
    ):
        assert secret not in body
