from __future__ import annotations

from services.gateway.app.api import _extract_har_cookie


def _har(*entries: tuple[str, str]) -> dict:
    return {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": url,
                        "headers": [{"name": "Cookie", "value": cookie}] if cookie else [],
                    }
                }
                for url, cookie in entries
            ]
        }
    }


def test_har_extracts_remanga_auth_token() -> None:
    payload = _har(
        ("https://example.com/api", "other=1"),
        ("https://remanga.org/api/v2/titles", "auth:token=abc; session=def"),
        ("https://remanga.org/media/1.jpg", "auth:token=abc; session=extra; more=1"),
    )

    cookie = _extract_har_cookie(payload, "remanga")

    assert cookie == "auth:token=abc; session=extra; more=1"


def test_har_ignores_other_sites() -> None:
    payload = _har(("https://mangalib.me/api", "token=abc"))

    assert _extract_har_cookie(payload, "remanga") is None


def test_har_returns_none_without_cookie_headers() -> None:
    payload = _har(("https://mangalib.me/", ""))

    assert _extract_har_cookie(payload, "mangalib") is None


def test_har_rejects_invalid_shape() -> None:
    assert _extract_har_cookie({"log": {}}, "remanga") is None
    assert _extract_har_cookie([], "remanga") is None
