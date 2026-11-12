"""A 20-30 query relevance set for the local catalogue.

``expected`` lists the titles that must be in the top-3.  ``all_expected`` is
used for genre/media queries where several equally valid titles may occupy the
top-3; in that case every top-3 result must belong to the expected set.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.fixtures.search_titles import TITLES

_ACTION = frozenset(spec.slug for spec in TITLES if "Экшен" in spec.genres)
_MANHWA = frozenset(spec.slug for spec in TITLES if spec.content_type == "манхва")


@dataclass(frozen=True)
class RelevanceCase:
    query: str
    expected: frozenset[str]
    all_expected: bool = False
    note: str = ""


RELEVANCE_CASES: tuple[RelevanceCase, ...] = (
    RelevanceCase("человек бензопила", frozenset({"chainsaw-man"}), note="russian title"),
    RelevanceCase("человек-бензопила", frozenset({"chainsaw-man"}), note="hyphen"),
    RelevanceCase("ЧЕЛОВЕК БЕНЗОПИЛА", frozenset({"chainsaw-man"}), note="case"),
    RelevanceCase("chainsaw man", frozenset({"chainsaw-man"}), note="english alt title"),
    RelevanceCase("chenso man", frozenset({"chainsaw-man"}), note="latin typo"),
    RelevanceCase("чензо мен", frozenset({"chainsaw-man"}), note="cyrillic typo"),
    RelevanceCase("человек бензопил", frozenset({"chainsaw-man"}), note="missing letter"),
    RelevanceCase("solo leveling", frozenset({"solo-leveling"}), note="english alt title"),
    RelevanceCase("поднятие уровня", frozenset({"solo-leveling"}), note="russian title"),
    RelevanceCase("соло левелинг", frozenset({"solo-leveling"}), note="translit"),
    RelevanceCase("overgeared", frozenset({"overgeared"}), note="english"),
    RelevanceCase("овергир", frozenset({"overgeared"}), note="russian translit"),
    RelevanceCase("jujutsu kaisen", frozenset({"jujutsu-kaisen"}), note="english alt"),
    RelevanceCase("магическая битва", frozenset({"jujutsu-kaisen"}), note="russian title"),
    RelevanceCase("тетрадь смерти", frozenset({"death-note"}), note="russian title"),
    RelevanceCase("death note", frozenset({"death-note"}), note="english title"),
    RelevanceCase("атака титанов", frozenset({"attack-on-titan"}), note="russian title"),
    RelevanceCase("attack on titan", frozenset({"attack-on-titan"}), note="english title"),
    RelevanceCase("ван пис", frozenset({"one-piece"}), note="translit typo"),
    RelevanceCase("one piece", frozenset({"one-piece"}), note="english title"),
    RelevanceCase("семья шпиона", frozenset({"spy-x-family"}), note="russian title"),
    RelevanceCase("spy family", frozenset({"spy-x-family"}), note="missing punctuation token"),
    RelevanceCase("всеведущий читатель", frozenset({"omniscient-reader"}), note="russian title"),
    RelevanceCase("omniscient reader", frozenset({"omniscient-reader"}), note="english short title"),
    RelevanceCase("возвращение секты хуа", frozenset({"mount-hua-sect"}), note="russian title"),
    RelevanceCase("боевик", _ACTION, all_expected=True, note="genre synonym"),
    RelevanceCase("манхва", _MANHWA, all_expected=True, note="media synonym"),
    RelevanceCase("читать человек бензопила", frozenset({"chainsaw-man"}), note="reading stopword"),
)
