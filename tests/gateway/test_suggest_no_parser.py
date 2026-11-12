from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from manga_common.schemas import SearchSuggestionOut, SuggestResponse
from services.gateway.app.api import router


class CatalogSpy:
    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []

    async def suggest(
        self, q: str, *, limit: int = 6, adult_allowed: bool = False
    ) -> SuggestResponse:
        self.queries.append((q, limit))
        return SuggestResponse(
            query=q,
            items=[
                SearchSuggestionOut(
                    id="00000000-0000-0000-0000-000000000001",
                    title="Человек-бензопила",
                    title_en="Chainsaw Man",
                    source="mangapoisk",
                    reason="alternative",
                )
            ],
            total=1,
        )


class ParserSpy:
    def __init__(self) -> None:
        self.search_calls = 0
        self.sources_calls = 0

    async def search(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.search_calls += 1
        raise AssertionError("suggestions must not call parser.search")

    async def sources(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.sources_calls += 1
        raise AssertionError("suggestions must not call parser.sources")


@pytest.mark.asyncio
async def test_gateway_suggest_never_touches_parser() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.catalog = CatalogSpy()
    app.state.parser = ParserSpy()
    app.state.library = object()
    app.state.media = object()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/manga/suggest", params={"q": "чензо мен", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["title"] == "Человек-бензопила"
    assert app.state.parser.search_calls == 0
    assert app.state.parser.sources_calls == 0
    assert app.state.catalog.queries == [("чензо мен", 5)]
