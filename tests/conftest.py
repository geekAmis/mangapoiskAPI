from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Prefer the packages from the checked-out worktree over any editable install
# left behind by another checkout, so the suite always tests this tree.
for _path in (ROOT, ROOT / "packages" / "manga_common"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT
