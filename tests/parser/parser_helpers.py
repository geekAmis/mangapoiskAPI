"""Reusable fixture helpers for parser tests."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def inertia_html(payload: dict[str, Any]) -> str:
    """Render a minimal MangaPoisk-like HTML shell around an Inertia payload."""

    encoded = html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><title>fixture</title></head>"
        f"<body><div id=\"app\" data-page=\"{encoded}\"></div></body></html>"
    )


def json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def mock_allow_robots(router: Any, host: str) -> Any:
    return router.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nAllow: /\n",
        )
    )
