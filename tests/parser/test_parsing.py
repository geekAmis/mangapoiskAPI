from __future__ import annotations

from services.parser.app.adapters.parsing import first_text


def test_first_text_decodes_entities_and_strips_tags() -> None:
    assert (
        first_text("  Магия   воды &mdash; <b>Лёд</b> &amp; снег  ")
        == "Магия воды — Лёд & снег"
    )


def test_first_text_skips_empty_values() -> None:
    assert first_text(None, "", "   ", "&amp;") == "&"


def test_first_text_keeps_scalar_values() -> None:
    assert first_text(42, "fallback") == "42"
