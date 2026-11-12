from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "manga_common"
# Worktrees share the developer's editable install in some environments; put
# the worktree's own shared package first so tests never import another branch.
for _path in (PACKAGE_ROOT, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT
