from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SERVICES = (
    "parser",
    "catalog",
    "library",
    "media",
    "control",
    "gateway",
    "comments",
    "notifier",
    "scheduler",
    "replica",
)


@pytest.mark.parametrize("service", SERVICES)
def test_service_main_imports_cleanly(service: str) -> None:
    """Catch conflict-induced missing symbols before a deploy.

    Each service is imported in a fresh interpreter with the same import layout
    used by its systemd unit: repository root, shared package and service dir.
    """

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(root / "packages" / "manga_common"),
            str(root),
            str(root / "services" / service),
        ]
    )
    env.setdefault("ENVIRONMENT", "test")
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, (
        f"{service} app.main import failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
