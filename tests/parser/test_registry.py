from __future__ import annotations

import pytest
from manga_common.errors import NotFoundError
from services.parser.app.registry import AdapterRegistry, build_registry
from services.parser.app.settings import ParserSettings


async def test_registry_lists_all_sources(settings, cache, client) -> None:
    registry = build_registry(client, settings, cache)
    assert registry.codes() == ["mangapoisk", "mangalib", "remanga", "readmanga", "mangadex"]
    infos = {info.code: info for info in registry.infos()}
    assert infos["mangapoisk"].enabled is True
    assert infos["mangalib"].enabled is True
    assert infos["remanga"].enabled is True
    assert infos["readmanga"].enabled is False
    assert infos["mangadex"].enabled is False
    assert infos["mangalib"].capabilities.pages is True
    assert infos["mangadex"].capabilities.pages is True


async def test_registry_requires_enabled_source(settings, cache, client) -> None:
    registry = build_registry(client, settings, cache)
    assert registry.require("MANGApoisk").info.code == "mangapoisk"
    assert registry.require("remanga").info.code == "remanga"
    with pytest.raises(NotFoundError) as disabled:
        registry.require("readmanga")
    assert disabled.value.code == "source_disabled"
    with pytest.raises(NotFoundError) as unknown:
        registry.require("does-not-exist")
    assert unknown.value.code == "source_not_found"


async def test_explicit_opt_in_enables_disabled_source(cache, client) -> None:
    opt_in = ParserSettings(
        _env_file=None,
        environment="test",
        parser_enabled_sources="remanga,readmanga",
    )
    registry = build_registry(client, opt_in, cache)
    infos = {info.code: info for info in registry.infos()}
    assert infos["remanga"].enabled is True
    assert infos["readmanga"].enabled is True
    assert infos["mangadex"].enabled is False
    assert registry.require("remanga").info.code == "remanga"


async def test_registry_infos_are_copies(settings, cache, client) -> None:
    registry = build_registry(client, settings, cache)
    info = registry.infos()[0]
    info.enabled = False
    assert registry.require("mangapoisk").info.enabled is True


async def test_empty_registry_require() -> None:
    registry = AdapterRegistry([])
    assert registry.codes() == []
    with pytest.raises(NotFoundError):
        registry.require("mangapoisk")
