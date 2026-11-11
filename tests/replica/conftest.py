from __future__ import annotations

from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest
from services.replica.app.config import ReplicaSettings


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., ReplicaSettings]:
    sequence = count(1)

    def factory(**overrides: object) -> ReplicaSettings:
        index = next(sequence)
        root = tmp_path / f"node-{index}"
        values: dict[str, object] = {
            "environment": "test",
            "log_level": "WARNING",
            "log_json": False,
            "internal_token": "test-internal-token",
            "replica_dir": str(root / "replica"),
            "data_root": str(root / "data"),
            "registry_url": "http://127.0.0.1:1/api/v1/registry",
            "sync_seconds": 1.0,
            "self_replica_url": f"http://self-{index}.invalid:8108",
            "sync_disabled": True,
        }
        values.update(overrides)
        return ReplicaSettings(**values)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def replica_settings(settings_factory: Callable[..., ReplicaSettings]) -> ReplicaSettings:
    return settings_factory()
