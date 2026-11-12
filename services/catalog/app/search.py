"""Catalogue search: normalization, transliteration, synonyms and ranking.

The catalogue stores a small, denormalised search document on every row.  The
document is produced entirely in Python so SQLite (tests, local installs) and
PostgreSQL behave the same way and no database extension is required for
correctness.  PostgreSQL additionally gets ``pg_trgm`` GIN indexes and a
``word_similarity`` candidate branch for large catalogues; see
``migrations.py``.

Design goals:
    * typo tolerance without an external search service;
    * Russian <-> Latin transliteration and consonant skeletons;
    * synonyms for media types and genre aliases;
    * deterministic ranking shared by the API and tests.

Nothing in this module performs I/O, so the ranking can be unit-tested on its
own and the repository can reuse it for the SQL pre-filter.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from .normalization import GENRE_LABELS, genre_key

MAX_QUERY_CHARS = 200
MAX_QUERY_TOKENS = 10
MAX_TOKEN_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_200
MAX_TERMS = 96
MIN_RELEVANCE_SCORE = 45.0
RELATIVE_RELEVANCE_CUTOFF = 0.28

# Bumped whenever the normalized document changes shape.  ``ensure_runtime_schema``
# marks older rows for the bounded background reindex so an algorithm change
# does not require a manual ``--force`` deploy step.
SEARCH_DOC_VERSION = 2

_WHITESPACE_RE = re.compile(r"\s+")
_CYRILLIC_RE = re.compile(r"[а-я]")
_LATIN_RE = re.compile(r"[a-z]")

# Query words that describe the act of reading rather than a title.  They are
# intentionally ignored: "читать человек бензопила" must behave like
# "человек бензопила".  "том"/"глава" are structural words in chapter queries;
# the catalogue itself has no chapter text in its search document.
STOPWORDS = frozenset(
    {
        "читать",
        "читка",
        "почитать",
        "прочитать",
        "чтение",
        "том",
        "тома",
        "томе",
        "томов",
        "томы",
        "глава",
        "главе",
        "главы",
        "главу",
        "глав",
    }
)

# Synonyms that change the candidate pool, not just the label.  Genres are
# covered by ``GENRE_ALIASES`` below (e.g. "боевик" -> "action").
MEDIA_SYNONYMS: dict[str, str] = {
    "манга": "manga",
    "manga": "manga",
    "манхва": "manhwa",
    "manhwa": "manhwa",
    "маньхуа": "manhua",
    "manhua": "manhua",
    "вебтун": "webtoon",
    "веб-тун": "webtoon",
    "webtoon": "webtoon",
    "комикс": "comic",
    "comics": "comic",
    "comic": "comic",
    "ранобэ": "novel",
    "новелла": "novel",
    "novel": "novel",
}

# Also accepted as separators inside a title: "человек-бензопила" is tokenised
# by the normalizer, so no special mapping is needed for hyphens.

_RU_TO_LAT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

# Longest digraphs first.  This is a deliberately simple phonetic mapping, not
# a scientific transliteration: it only needs to put Russian and Latin spellings
# of the same title close enough for the fuzzy ranker.
_EN_TO_RU_RULES: tuple[tuple[str, str], ...] = (
    ("shch", "щ"),
    ("sch", "щ"),
    ("tch", "ч"),
    ("tion", "шн"),
    ("sion", "жн"),
    ("igh", "ай"),
    ("ch", "ч"),
    ("sh", "ш"),
    ("th", "т"),
    ("ph", "ф"),
    ("ck", "к"),
    ("wh", "в"),
    ("qu", "кв"),
    ("oo", "у"),
    ("ee", "и"),
    ("ea", "и"),
    ("ai", "ей"),
    ("ay", "ей"),
    ("ey", "ей"),
    ("oy", "ой"),
    ("oi", "ой"),
    ("ou", "оу"),
    ("ow", "оу"),
    ("au", "о"),
    ("aw", "о"),
    ("ie", "и"),
    ("kn", "н"),
    ("wr", "р"),
)

_EN_TO_RU: dict[str, str] = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "дж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "й",
    "z": "з",
}

_RU_VOWELS = frozenset("аеиоуыэюя")
_EN_VOWELS = frozenset("aeiouyw")

# Canonical spelling for the typo pairs that matter for Russian/Latin manga
# queries: з/с/ц, ч/ц, е/э/и/ы/й and о/а.  This is deliberately a *skeleton*
# (vowels are dropped as well), so it widens candidate recall without making
# the main token index or the exact-match ranker fuzzy.
_CONFUSABLE_CANON: dict[str, str] = {
    "з": "с",
    "с": "с",
    "ц": "с",
    "ч": "ц",
    "ш": "ш",
    "щ": "ш",
    "е": "е",
    "э": "е",
    "и": "и",
    "ы": "и",
    "й": "и",
    "о": "а",
    "а": "а",
    "z": "s",
    "s": "s",
    "e": "e",
    "i": "i",
    "o": "a",
    "a": "a",
}

# Common one-character typing confusions.  Both dialects add these terms to the
# candidate pre-filter; PostgreSQL's trigram GIN index accelerates the LIKEs.
_CONFUSABLES: dict[str, str] = {
    "а": "ои",
    "б": "п",
    "в": "ф",
    "г": "к",
    "д": "т",
    "е": "иэа",
    "ё": "е",
    "ж": "ш",
    "з": "сц",
    "и": "ей",
    "й": "и",
    "к": "г",
    "л": "р",
    "м": "н",
    "н": "м",
    "о": "ау",
    "п": "б",
    "р": "л",
    "с": "зц",
    "т": "д",
    "у": "ою",
    "ф": "в",
    "х": "к",
    "ц": "сч",
    "ч": "шц",
    "ш": "жч",
    "щ": "ш",
    "ы": "и",
    "ь": "",
    "ъ": "",
    "э": "е",
    "ю": "у",
    "я": "а",
    "a": "oe",
    "b": "p",
    "c": "ks",
    "d": "t",
    "e": "ia",
    "f": "v",
    "g": "k",
    "h": "x",
    "i": "ey",
    "j": "g",
    "k": "cg",
    "l": "r",
    "m": "n",
    "n": "m",
    "o": "au",
    "p": "b",
    "q": "k",
    "r": "l",
    "s": "zc",
    "t": "d",
    "u": "o",
    "v": "f",
    "w": "v",
    "x": "ks",
    "y": "ie",
    "z": "s",
}


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_search_text(value: object | None) -> str:
    """Lower-case, accent/``ё``-insensitive, punctuation-free search text."""

    if value is None:
        return ""
    text = _strip_accents(str(value)).casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def tokenize(value: object | None, *, max_tokens: int | None = None) -> list[str]:
    text = normalize_search_text(value)
    if not text:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in text.split():
        token = raw[:MAX_TOKEN_CHARS]
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if max_tokens is not None and len(tokens) >= max_tokens:
            break
    return tokens


def transliterate_ru(text: str) -> str:
    return "".join(_RU_TO_LAT.get(char, char) for char in text)


def _phonetic_word(word: str) -> str:
    if not word:
        return ""
    # English silent final "e": "levels" stays, "make" -> "mak".
    if len(word) > 3 and word.endswith("e") and word[-2] not in _EN_VOWELS:
        word = word[:-1]
    result: list[str] = []
    index = 0
    while index < len(word):
        for source, target in _EN_TO_RU_RULES:
            if word.startswith(source, index):
                result.append(target)
                index += len(source)
                break
        else:
            char = word[index]
            result.append(_EN_TO_RU.get(char, char))
            index += 1
    return "".join(result)


def phonetic_latin(text: str) -> str:
    """Approximate Cyrillic reading of a Latin title ("chainsaw" -> "чейнсо")."""

    words = text.split()
    return " ".join(_phonetic_word(word) for word in words)


def _skeleton_word(word: str, *, cyrillic: bool) -> str:
    if not word:
        return ""
    vowels = _RU_VOWELS if cyrillic else _EN_VOWELS
    first = word[0]
    rest = "".join(char for char in word[1:] if char not in vowels)
    return first + rest


def consonant_skeleton(text: str, *, cyrillic: bool | None = None) -> str:
    """Keep the first character and drop vowels from the rest of each word."""

    if not text:
        return ""
    if cyrillic is None:
        cyrillic = bool(_CYRILLIC_RE.search(text))
    words = text.split()
    return " ".join(_skeleton_word(word, cyrillic=cyrillic) for word in words)


def _confusable_word(word: str) -> str:
    if not word:
        return ""
    cyrillic = bool(_CYRILLIC_RE.search(word))
    vowels = _RU_VOWELS if cyrillic else _EN_VOWELS
    first = _CONFUSABLE_CANON.get(word[0], word[0])
    rest = [
        _CONFUSABLE_CANON.get(char, char)
        for char in word[1:]
        if char not in vowels
    ]
    return first + "".join(rest)


def confusable_skeleton(text: str) -> str:
    """Vowel-free skeleton with Russian sibilant/vowel typo classes collapsed.

    ``чензо``/``ченсо`` become ``цнс`` and their transliterations
    ``chenzo``/``chenso`` become ``chns``; Latin ``chainsaw`` also becomes
    ``chns``.  Query skeletons match exactly/prefix only, so normal fuzzy
    ranking keeps its precision.
    """

    if not text:
        return ""
    return " ".join(_confusable_word(word) for word in text.split())


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _variants_for_text(
    value: object | None,
    *,
    with_skeleton: bool = True,
    with_confusable: bool = True,
) -> list[str]:
    """Normalized text plus cross-script and consonant-skeleton variants."""

    normalized = normalize_search_text(value)
    if not normalized:
        return []
    variants: list[str] = [normalized]
    if _CYRILLIC_RE.search(normalized):
        latin = transliterate_ru(normalized)
        if latin and latin != normalized:
            variants.append(latin)
            if with_skeleton:
                skeleton = consonant_skeleton(latin, cyrillic=False)
                variants.append(skeleton)
                variants.append(skeleton.replace(" ", ""))
                if with_confusable:
                    confusable = confusable_skeleton(latin)
                    variants.append(confusable)
                    variants.append(confusable.replace(" ", ""))
    if _LATIN_RE.search(normalized):
        cyrillic = phonetic_latin(normalized)
        if cyrillic and cyrillic != normalized:
            variants.append(cyrillic)
            if with_skeleton:
                skeleton = consonant_skeleton(cyrillic, cyrillic=True)
                variants.append(skeleton)
                variants.append(skeleton.replace(" ", ""))
                if with_confusable:
                    confusable = confusable_skeleton(cyrillic)
                    variants.append(confusable)
                    variants.append(confusable.replace(" ", ""))
    if with_skeleton:
        skeleton = consonant_skeleton(
            normalized, cyrillic=bool(_CYRILLIC_RE.search(normalized))
        )
        variants.append(skeleton)
        variants.append(skeleton.replace(" ", ""))
        if with_confusable:
            confusable = confusable_skeleton(normalized)
            variants.append(confusable)
            variants.append(confusable.replace(" ", ""))
    return _unique(variants)


def _exact_skeleton_variants_for_text(value: object | None) -> list[str]:
    """Skeletons used as exact (non-fuzzy) query variants.

    Skeletons are excellent at vowel-insensitive and sibilant-confusion
    matching, but as *fuzzy* tokens they also make short unrelated words
    ("манхва" vs "Менхера") look similar.  Keeping them exact preserves the
    recall win and removes that precision loss.
    """

    normalized = normalize_search_text(value)
    if not normalized:
        return []
    variants: list[str] = []
    sources = [normalized]
    if _CYRILLIC_RE.search(normalized):
        latin = transliterate_ru(normalized)
        if latin and latin != normalized:
            sources.append(latin)
    if _LATIN_RE.search(normalized):
        cyrillic = phonetic_latin(normalized)
        if cyrillic and cyrillic != normalized:
            sources.append(cyrillic)
    for source in sources:
        cyrillic = bool(_CYRILLIC_RE.search(source))
        for skeleton in (
            consonant_skeleton(source, cyrillic=cyrillic),
            confusable_skeleton(source),
        ):
            if len(skeleton.replace(" ", "")) >= 3:
                variants.append(skeleton)
                variants.append(skeleton.replace(" ", ""))
    return _unique(variants)


def search_document_tokens(values: Sequence[object | None], *, with_skeleton: bool = True) -> str:
    tokens: list[str] = []
    for value in values:
        for variant in _variants_for_text(value, with_skeleton=with_skeleton):
            tokens.extend(tokenize(variant))
    return " ".join(_unique(tokens))


def _people_values(value: object | None) -> list[str]:
    """Normalize a scalar/list of author or artist names."""

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        text = str(value.get("name") or value.get("label") or "").strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = str(item.get("name") or item.get("label") or "").strip()
            else:
                text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def normalize_people(value: object | None) -> list[str]:
    """Public wrapper used by import/backfill code."""

    return _people_values(value)


def _metadata_people(metadata: Mapping[str, Any] | None, *keys: str) -> list[str]:
    if not isinstance(metadata, Mapping):
        return []
    result: list[str] = []
    for key in keys:
        result.extend(_people_values(metadata.get(key)))
    return result


def metadata_people(metadata: Mapping[str, Any] | None, *keys: str) -> list[str]:
    """Public helper for the enrichment/backfill fallback path."""

    return _metadata_people(metadata, *keys)


def _people_for_fields(
    authors: Sequence[str] | None,
    artists: Sequence[str] | None,
    metadata: Mapping[str, Any] | None,
) -> list[str]:
    """Explicit columns win, but legacy ``metadata`` people are still indexed.

    The union keeps a row searchable after an adapter starts writing the new
    columns and while older rows only have ``metadata.authors`` from the v1.2
    import path.
    """

    people = [
        *_people_values(list(authors or ())),
        *_people_values(list(artists or ())),
    ]
    people.extend(_metadata_people(metadata, "authors", "author", "artists", "artist"))
    return _unique(people)


def build_search_fields(
    *,
    title: str | None,
    title_en: str | None,
    title_alt: str | None,
    genres: Sequence[str] | None,
    content_type: str | None,
    description: str | None,
    metadata: Mapping[str, Any] | None = None,
    authors: Sequence[str] | None = None,
    artists: Sequence[str] | None = None,
) -> dict[str, str]:
    """Build the denormalised search document for one catalogue row."""

    people = _people_for_fields(authors, artists, metadata)
    title_doc = search_document_tokens([title])
    alt_doc = search_document_tokens([title_en, title_alt])
    author_doc = search_document_tokens(people)
    names_doc = " ".join(_unique([title_doc, alt_doc]))

    genre_values: list[str] = []
    for label in genres or []:
        genre_values.append(str(label))
        slug = genre_key(label)
        if slug:
            genre_values.append(slug)
            known = GENRE_LABELS.get(slug)
            if known:
                genre_values.append(known)
    content_value = normalize_search_text(content_type)
    if content_value:
        genre_values.append(content_value)
        media = MEDIA_SYNONYMS.get(content_value)
        if media:
            genre_values.append(media)
    meta_doc = search_document_tokens(genre_values)

    description_doc = normalize_search_text(description)[:MAX_DESCRIPTION_CHARS]
    blob = " ".join(
        _unique(
            [
                *tokenize(names_doc),
                *tokenize(author_doc),
                *tokenize(meta_doc),
                *tokenize(description_doc),
            ]
        )
    )
    return {
        "search_title": title_doc[:8000],
        "search_alt": alt_doc[:8000],
        "search_author": author_doc[:8000],
        "search_names": names_doc[:12000],
        "search_meta": meta_doc[:8000],
        "search_description": description_doc[:MAX_DESCRIPTION_CHARS],
        "search_blob": blob[:20000],
    }


@dataclass(frozen=True)
class QueryToken:
    text: str
    variants: tuple[str, ...]
    # Confusable skeletons match only exactly/prefix, never through fuzzy
    # edit distance.  That keeps ``манхва`` from fuzzy-matching ``Менхера``
    # while still letting ``чензо`` reach ``Чейнсо``.
    exact_variants: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchQuery:
    raw: str
    normalized: str
    tokens: tuple[QueryToken, ...]
    variants: tuple[str, ...]
    exact_variants: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.normalized or not self.tokens


def analyze_query(raw: str | None) -> SearchQuery:
    """Normalize a user query and expand it with synonyms/script variants."""

    source = (raw or "").strip()
    normalized = normalize_search_text(source)[:MAX_QUERY_CHARS]
    if not normalized:
        return SearchQuery(raw=source, normalized="", tokens=(), variants=())

    words = tokenize(normalized, max_tokens=MAX_QUERY_TOKENS)
    tokens: list[QueryToken] = []
    for word in words:
        if word in STOPWORDS:
            continue
        variants: list[str] = [word]
        media = MEDIA_SYNONYMS.get(word)
        if media:
            variants.append(media)
        canonical = genre_key(word)
        if canonical:
            variants.append(canonical)
            label = GENRE_LABELS.get(canonical)
            if label:
                variants.append(normalize_search_text(label))
        variants.extend(
            _variants_for_text(word, with_skeleton=False, with_confusable=False)
        )
        exact_variants = _exact_skeleton_variants_for_text(word)
        tokens.append(
            QueryToken(
                text=word,
                variants=tuple(_unique(variants)),
                exact_variants=tuple(exact_variants),
            )
        )

    if not tokens:
        return SearchQuery(raw=source, normalized="", tokens=(), variants=())

    normalized_tokens = " ".join(token.text for token in tokens)
    full_variants: list[str] = [normalized_tokens]
    full_variants.extend(
        _variants_for_text(normalized_tokens, with_skeleton=False, with_confusable=False)
    )
    exact_variants = _exact_skeleton_variants_for_text(normalized_tokens)
    return SearchQuery(
        raw=source,
        normalized=normalized_tokens,
        tokens=tuple(tokens),
        variants=tuple(_unique(full_variants)),
        exact_variants=tuple(exact_variants),
    )


def _trigrams(text: str) -> frozenset[str]:
    padded = f"  {text} "
    if len(padded) < 3:
        return frozenset()
    return frozenset(padded[index : index + 3] for index in range(len(padded) - 2))


@lru_cache(maxsize=50_000)
def _trigram_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    first = _trigrams(left)
    second = _trigrams(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _max_edits(length: int) -> int:
    # Three-letter tokens are common in short queries ("мен", "man"); allow one
    # edit there.  Two-letter tokens stay exact/prefix-only to avoid noise.
    if length < 3:
        return 0
    if length <= 7:
        return 1
    if length <= 12:
        return 2
    return 3


@lru_cache(maxsize=50_000)
def _levenshtein(left: str, right: str, max_distance: int) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    if not left or not right:
        return max_distance + 1
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        row_min = row
        for column, right_char in enumerate(right, 1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[column] + 1,
                current[column - 1] + 1,
                previous[column - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def fuzzy_similarity(left: str, right: str) -> float:
    """Similarity in ``[0, 1]`` with a length-aware edit-distance threshold."""

    if left == right:
        return 1.0
    if len(left) < 3 or len(right) < 3:
        return 0.0
    limit = _max_edits(max(len(left), len(right)))
    if limit == 0:
        return 0.0
    if abs(len(left) - len(right)) > limit:
        return 0.0
    distance = _levenshtein(left, right, limit)
    if distance <= limit:
        return 1.0 - distance / max(len(left), len(right))
    similarity = _trigram_similarity(left, right)
    return similarity if similarity >= 0.55 else 0.0


@dataclass(frozen=True)
class _FieldIndex:
    """Token lookup structures for one search field of one catalogue row."""

    tokens: tuple[str, ...]
    token_set: frozenset[str]
    by_first: Mapping[str, tuple[str, ...]]


@lru_cache(maxsize=20_000)
def _index_field(text: str) -> _FieldIndex:
    tokens = tuple(tokenize(text))
    buckets: dict[str, list[str]] = {}
    for token in tokens:
        buckets.setdefault(token[0], []).append(token)
    return _FieldIndex(
        tokens=tokens,
        token_set=frozenset(tokens),
        by_first={key: tuple(value) for key, value in buckets.items()},
    )


def _best_match(variant: str, field: _FieldIndex, *, fuzzy: bool) -> tuple[int, float]:
    """Return ``(level, similarity)`` for one query variant in one field."""

    if not variant or not field.tokens:
        return 0, 0.0
    if variant in field.token_set:
        return 3, 1.0
    same_first = field.by_first.get(variant[0], ())
    if not same_first:
        return 0, 0.0
    if len(variant) <= 3:
        # Thin queries ("ч", "че", "ман") are prefix filters, not fuzzy text.
        for token in same_first:
            if len(token) > len(variant) and token.startswith(variant):
                return 2, len(variant) / len(token)
    if len(variant) >= 4:
        for token in same_first:
            shorter, longer = (variant, token) if len(variant) <= len(token) else (token, variant)
            if len(shorter) >= 4 and longer.startswith(shorter):
                ratio = len(shorter) / len(longer)
                if ratio >= 0.6:
                    return 2, ratio
    if not fuzzy:
        return 0, 0.0
    best = 0.0
    for token in same_first:
        if abs(len(token) - len(variant)) > _max_edits(max(len(token), len(variant))):
            continue
        similarity = fuzzy_similarity(token, variant)
        if similarity > best:
            best = similarity
    if best >= 0.58:
        return 1, best
    return 0, 0.0


_FIELD_WEIGHTS = {
    "title": 1.0,
    "alt": 0.82,
    "author": 0.62,
    "meta": 0.38,
    "description": 0.12,
}


@lru_cache(maxsize=8_000)
def _legacy_fields(
    title: str | None,
    title_en: str | None,
    title_alt: str | None,
    genres: tuple[str, ...],
    content_type: str | None,
    description: str | None,
    metadata_json: str,
    authors: tuple[str, ...] = (),
    artists: tuple[str, ...] = (),
) -> dict[str, str]:
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except (TypeError, ValueError):
        metadata = {}
    return build_search_fields(
        title=title,
        title_en=title_en,
        title_alt=title_alt,
        genres=list(genres),
        content_type=content_type,
        description=description,
        metadata=metadata if isinstance(metadata, Mapping) else {},
        authors=list(authors),
        artists=list(artists),
    )


def ranking_view(manga: Any) -> Any:
    """Return a row with a search document, building it on demand for legacy rows.

    During the background backfill some rows still have ``search_indexed``
    false.  They must remain searchable through their legacy title/description
    columns, but the ranker needs the same normalized fields as indexed rows.
    The per-row computation is cached because the row does not change until the
    worker flips it to indexed.
    """

    if getattr(manga, "search_indexed", True):
        return manga
    genres = tuple(str(item) for item in (getattr(manga, "genres", None) or ()))
    metadata = getattr(manga, "metadata_json", None) or {}
    metadata_json = (
        json.dumps(metadata, sort_keys=True, ensure_ascii=False, default=str)
        if isinstance(metadata, Mapping)
        else "{}"
    )
    authors = tuple(str(item) for item in (getattr(manga, "authors", None) or ()))
    artists = tuple(str(item) for item in (getattr(manga, "artists", None) or ()))
    fields = _legacy_fields(
        getattr(manga, "title", None),
        getattr(manga, "title_en", None),
        getattr(manga, "title_alt", None),
        genres,
        getattr(manga, "content_type", None),
        getattr(manga, "description", None),
        metadata_json,
        authors,
        artists,
    )
    return SimpleNamespace(
        **fields,
        rating=getattr(manga, "rating", None),
        rating_count=getattr(manga, "rating_count", None),
        chapters_count=getattr(manga, "chapters_count", 0),
        group_key=getattr(manga, "group_key", None),
        id=getattr(manga, "id", None),
        search_indexed=False,
    )


def rank_manga(query: SearchQuery, manga: Any) -> tuple[float, str]:
    """Score one catalogue row.  Higher is better; second value is the reason."""

    if query.is_empty:
        return 0.0, "empty"

    document = ranking_view(manga)
    score = 0.0
    reason = "title"
    reason_weight = 0.0
    fields = (
        ("title", getattr(document, "search_title", "") or "", True),
        ("alt", getattr(document, "search_alt", "") or "", True),
        ("author", getattr(document, "search_author", "") or "", True),
        ("meta", getattr(document, "search_meta", "") or "", False),
    )
    normalized_query = query.normalized
    for field_name, field_text, fuzzy in fields:
        if not field_text:
            continue
        weight = _FIELD_WEIGHTS[field_name]
        field = _index_field(field_text)
        field_score = 0.0

        padded = f" {field_text} "
        if normalized_query and f" {normalized_query} " in padded:
            field_score += 700 * weight
        phrase_bonus = 0.0
        for variant in query.variants[1:]:
            if len(variant) < 4:
                continue
            if f" {variant} " in padded:
                phrase_bonus = 360.0
                break
            if not fuzzy:
                continue
            for token in field.by_first.get(variant[0], ()):
                if abs(len(token) - len(variant)) > 3:
                    continue
                similarity = fuzzy_similarity(variant, token)
                phrase_bonus = max(phrase_bonus, 200.0 * similarity)
        for variant in query.exact_variants:
            if f" {variant} " in padded:
                phrase_bonus = max(phrase_bonus, 360.0)
                break
        field_score += phrase_bonus * weight

        matched = 0
        for token in query.tokens:
            best_level = 0
            best_similarity = 0.0
            for variant in token.variants:
                level, similarity = _best_match(variant, field, fuzzy=fuzzy)
                if level > best_level or (level == best_level and similarity > best_similarity):
                    best_level = level
                    best_similarity = similarity
                if best_level == 3:
                    break
            if best_level != 3:
                for variant in token.exact_variants:
                    level, similarity = _best_match(variant, field, fuzzy=False)
                    if level > best_level or (
                        level == best_level and similarity > best_similarity
                    ):
                        best_level = level
                        best_similarity = similarity
                    if best_level == 3:
                        break
            if best_level == 0:
                continue
            matched += 1
            if best_level == 3:
                field_score += 130 * weight
            elif best_level == 2:
                field_score += 92 * weight
            else:
                field_score += 72 * best_similarity * weight
        if matched == len(query.tokens) and len(query.tokens) > 0:
            field_score += 110 * weight
        elif matched:
            field_score += 22 * weight * (matched / len(query.tokens))

        score += field_score
        if field_score > reason_weight:
            reason_weight = field_score
            reason = field_name

    description_text = getattr(document, "search_description", "") or ""
    if (
        description_text
        and len(normalized_query) >= 4
        and f" {normalized_query} " in f" {description_text} "
    ):
        score += 45.0
        if reason_weight == 0:
            reason = "description"

    rating = float(getattr(document, "rating", None) or 0.0)
    rating_count = int(getattr(document, "rating_count", None) or 0)
    chapters = int(getattr(document, "chapters_count", None) or 0)
    # Capped popularity is a tie-breaker only; a strong text match always wins.
    score += min(24.0, math.log1p(max(0, rating_count)) * 2.2 + max(0.0, rating) * 1.1)
    score += min(4.0, math.log1p(max(0, chapters)) * 0.4)
    return score, reason


def rank_rows(query: SearchQuery, rows: Sequence[Any]) -> list[tuple[Any, float, str]]:
    ranked = [(row, *rank_manga(query, row)) for row in rows]
    ranked.sort(
        key=lambda item: (
            -item[1],
            -int(getattr(item[0], "chapters_count", 0) or 0),
            -float(getattr(item[0], "rating", 0) or 0),
            -int(getattr(item[0], "rating_count", 0) or 0),
        )
    )
    return ranked


def dedupe_ranked_groups(
    ranked: Sequence[tuple[Any, float, str]],
) -> list[tuple[Any, float, str]]:
    """Keep the best-scoring source variant for every title group."""

    result: list[tuple[Any, float, str]] = []
    seen: set[str] = set()
    for row, score, reason in ranked:
        group = getattr(row, "group_key", None) or str(getattr(row, "id", ""))
        if group in seen:
            continue
        seen.add(group)
        result.append((row, score, reason))
    return result


def token_coverage(query: SearchQuery, manga: Any) -> int:
    """How many query tokens have at least one match in title/alt/meta."""

    document = ranking_view(manga)
    fields = (
        (_index_field(getattr(document, "search_title", "") or ""), True),
        (_index_field(getattr(document, "search_alt", "") or ""), True),
        (_index_field(getattr(document, "search_author", "") or ""), True),
        (_index_field(getattr(document, "search_meta", "") or ""), False),
    )
    matched = 0
    for token in query.tokens:
        hit = False
        for field, fuzzy in fields:
            for variant in token.variants:
                if _best_match(variant, field, fuzzy=fuzzy)[0] > 0:
                    hit = True
                    break
            if hit:
                break
            for variant in token.exact_variants:
                if _best_match(variant, field, fuzzy=False)[0] > 0:
                    hit = True
                    break
            if hit:
                break
        if hit:
            matched += 1
    return matched


def filter_relevant(
    ranked: Sequence[tuple[Any, float, str]],
) -> list[tuple[Any, float, str]]:
    """Drop candidates that only matched a broad 2/3-character LIKE term.

    The SQL pre-filter is intentionally permissive (it must not miss typos).
    A relative cut-off removes the long tail without making relevance depend on
    catalogue size, while the absolute floor stops popularity-only rows from
    leaking into results for one-word queries.
    """

    if not ranked:
        return []
    best = ranked[0][1]
    cutoff = max(MIN_RELEVANCE_SCORE, best * RELATIVE_RELEVANCE_CUTOFF)
    return [item for item in ranked if item[1] >= cutoff]


def _deletions(token: str) -> list[str]:
    if len(token) < 3:
        return []
    # One deletion catches most single extra/missing character typos.
    return [token[:index] + token[index + 1 :] for index in range(len(token))]


def _substitutions(token: str) -> list[str]:
    if len(token) < 3:
        return []
    result: list[str] = []
    for index, char in enumerate(token):
        for replacement in _CONFUSABLES.get(char, ""):
            candidate = token[:index] + replacement + token[index + 1 :]
            if candidate and candidate != token:
                result.append(candidate)
    return result


def expansion_terms(query: SearchQuery, *, dialect: str) -> list[str]:
    """LIKE terms for the SQL candidate pre-filter.

    Long, specific terms are kept first so a capped list still contains the
    useful ones.  PostgreSQL and SQLite both get confusable substitutions and
    the confusable skeleton variants; the trigram GIN index accelerates the
    resulting ``LIKE '%term%'`` on PostgreSQL.
    """

    if query.is_empty:
        return []
    terms: set[str] = set()
    for token in query.tokens:
        for variant in token.variants:
            if not variant:
                continue
            if len(variant) == 1:
                terms.add(variant)
                continue
            terms.add(variant)
            if len(variant) > 3:
                terms.add(variant[:3])
                terms.add(variant[-3:])
            if len(variant) >= 4:
                terms.update(_deletions(variant))
                # Both dialects need the confusable substitutions: PostgreSQL
                # has no FTS mirror and its LIKE pre-filter is the only way a
                # typo can become a candidate before Python reranks it.
                terms.update(_substitutions(variant))
            elif len(variant) == 3:
                terms.add(variant[:2])
                terms.update(_substitutions(variant))
        for variant in token.exact_variants:
            if len(variant) >= 3:
                terms.add(variant)
                terms.add(variant.replace(" ", ""))
    for variant in query.variants:
        if len(variant) >= 3:
            terms.add(variant)
            if len(variant) >= 5:
                terms.add(variant[:3])
                terms.add(variant[-3:])
    for variant in query.exact_variants:
        if len(variant) >= 3:
            terms.add(variant)
            terms.add(variant.replace(" ", ""))
    ordered = sorted(terms, key=lambda item: (-len(item), item))
    return ordered[:MAX_TERMS]


def fts_match_query(query: SearchQuery) -> str:
    """FTS5 MATCH expression for the SQLite candidate pre-filter."""

    tokens: list[str] = []
    seen: set[str] = set()
    for term in expansion_terms(query, dialect="sqlite"):
        for token in tokenize(term):
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    tokens.sort(key=lambda item: (-len(item), item))
    return " OR ".join(f'"{token}"*' for token in tokens[:MAX_TERMS])


def suggestion_reason(reason: str) -> str:
    return {
        "title": "title",
        "alt": "alternative",
        "author": "author",
        "meta": "genre",
        "description": "description",
    }.get(reason, "title")


def describe_query(raw: str | None) -> dict[str, Any]:
    """Small diagnostic helper used by the benchmark and tests."""

    query = analyze_query(raw)
    return {
        "raw": query.raw,
        "normalized": query.normalized,
        "tokens": [token.text for token in query.tokens],
        "variants": list(query.variants),
        "exact_variants": list(query.exact_variants),
        "empty": query.is_empty,
    }
