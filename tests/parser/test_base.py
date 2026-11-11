from __future__ import annotations

import httpx
import pytest
import respx
from manga_common.errors import ForbiddenError, ValidationError
from services.parser.app.adapters.base import RobotsPolicy
from services.parser.app.adapters.mangapoisk import MangaPoiskAdapter


def test_robots_policy_uses_most_specific_rule() -> None:
    policy = RobotsPolicy.parse(
        """
        User-agent: *
        Disallow: /private
        Allow: /private/public
        Disallow: /*/commentsBlock
        """
    )
    assert policy.allows("/")
    assert policy.allows("/manga/example")
    assert policy.allows("/private/public/page")
    assert not policy.allows("/private/secret")
    assert not policy.allows("/manga/example/commentsBlock")


def test_cache_key_contains_source_and_normalised_params(settings, cache, client) -> None:
    adapter = MangaPoiskAdapter(client, settings, cache)
    first = adapter.cache_id("search", "  Overgeared ", 1)
    second = adapter.cache_id("search", "overgeared", 1)
    assert first == second
    assert first.startswith("parser:mangapoisk:search")


async def test_robots_network_error_fails_open(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get("https://mangapoisk.me/robots.txt").mock(
            side_effect=httpx.ConnectError("network down")
        )
        adapter = MangaPoiskAdapter(client, settings, cache)
        await adapter.ensure_robots_allowed("/manga/example")


async def test_robots_http_error_fails_closed(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get("https://mangapoisk.me/robots.txt").mock(
            return_value=httpx.Response(500, text="server error")
        )
        adapter = MangaPoiskAdapter(client, settings, cache)
        with pytest.raises(ForbiddenError) as error:
            await adapter.ensure_robots_allowed("/manga/example")
        assert error.value.code == "robots_disallowed"


def test_url_outside_allow_list_is_rejected(settings, cache, client) -> None:
    adapter = MangaPoiskAdapter(client, settings, cache)
    with pytest.raises(ValidationError) as error:
        adapter.assert_allowed_url("https://evil.example/manga/example")
    assert error.value.code == "url_host_not_allowed"
