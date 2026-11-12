from __future__ import annotations

import re

# Canonical status values follow the frontend/API enum.  Every group also
# accepts the Russian labels that upstream adapters store in the catalogue.
_STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "ongoing": (
        "ongoing",
        "releasing",
        "publishing",
        "выходит",
        "онгоинг",
        "продолжается",
        "продолжение",
        "в процессе",
    ),
    "completed": (
        "completed",
        "complete",
        "finished",
        "завершен",
        "завершено",
        "завершена",
        "завершенный",
        "закончен",
        "закончено",
    ),
    "announced": (
        "announced",
        "upcoming",
        "tba",
        "анонс",
        "анонсирован",
        "анонсировано",
        "анонсируется",
        "ожидается",
        "скоро",
    ),
    "dropped": (
        "dropped",
        "брошен",
        "брошено",
        "заброшен",
        "заброшено",
        "заброшена",
    ),
    "paused": (
        "paused",
        "hiatus",
        "on hold",
        "на паузе",
        "пауза",
        "приостановлен",
        "приостановлено",
        "приостановлена",
        "заморожен",
        "заморожено",
    ),
    "cancelled": (
        "cancelled",
        "canceled",
        "отменен",
        "отменено",
        "отменена",
    ),
    "licensed": (
        "licensed",
        "лицензировано",
        "лицензирован",
        "лицензирована",
    ),
    "unknown": (
        "unknown",
        "неизвестно",
        "неизвестен",
        "неизвестный",
    ),
}

STATUS_ALIASES: dict[str, str] = {
    alias: canonical for canonical, aliases in _STATUS_GROUPS.items() for alias in aliases
}


# Canonical genre slugs with a Russian label and every spelling seen in the
# Russian sources.  The alias table is deliberately data-only so new source
# labels can be added without touching filtering code.
_GENRE_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "action": ("Экшен", ("action", "экшен", "боевик", "боевики")),
    "adventure": ("Приключения", ("adventure", "приключения", "приключение")),
    "comedy": ("Комедия", ("comedy", "комедия")),
    "drama": ("Драма", ("drama", "драма")),
    "fantasy": (
        "Фэнтези",
        ("fantasy", "фэнтези", "heroic_fantasy", "героическое фэнтези", "фентези"),
    ),
    "horror": ("Ужасы", ("horror", "ужасы", "хоррор", "мистический хоррор")),
    "mecha": ("Меха", ("mecha", "меха", "роботы")),
    "mystery": ("Мистика", ("mystery", "мистика", "детектив", "загадка")),
    "romance": ("Романтика", ("romance", "романтика", "любовь")),
    "sci-fi": (
        "Научная фантастика",
        ("sci-fi", "sci_fi", "science_fiction", "научная фантастика", "фантастика"),
    ),
    "slice-of-life": (
        "Повседневность",
        ("slice-of-life", "slice_of_life", "повседневность", "повседневная жизнь"),
    ),
    "sports": ("Спорт", ("sports", "спорт")),
    "supernatural": (
        "Сверхъестественное",
        ("supernatural", "сверхъестественное", "мистическое"),
    ),
    "thriller": ("Триллер", ("thriller", "триллер")),
    "psychological": (
        "Психологическое",
        ("psychological", "психологическое", "психология"),
    ),
    "historical": ("Историческое", ("historical", "историческое", "история")),
    "isekai": ("Исэкай", ("isekai", "исэкай", "исекай")),
    "martial-arts": (
        "Боевые искусства",
        ("martial-arts", "martial_arts", "боевые искусства", "кунг-фу", "кунг фу"),
    ),
    "school": ("Школа", ("school", "школа", "школьная жизнь")),
    "shounen": ("Сёнэн", ("shounen", "shonen", "сёнэн", "сенен", "сёнен")),
    "seinen": ("Сэйнэн", ("seinen", "сэйнэн", "сейнен")),
    "shoujo": ("Сёдзё", ("shoujo", "сёдзё", "седзе", "сёдзе")),
    "josei": ("Дзёсэй", ("josei", "дзёсэй", "дзесей")),
    "ecchi": ("Этти", ("ecchi", "этти", "эчи")),
    "harem": ("Гарем", ("harem", "гарем")),
    "military": ("Военное", ("military", "военное", "война")),
    "music": ("Музыка", ("music", "музыка")),
    "parody": ("Пародия", ("parody", "пародия")),
    "post-apocalyptic": (
        "Постапокалипсис",
        ("post-apocalyptic", "post_apocalyptic", "постапокалипсис", "апокалипсис"),
    ),
    "reincarnation": (
        "Реинкарнация",
        ("reincarnation", "реинкарнация", "перерождение"),
    ),
    "demons": ("Демоны", ("demons", "демоны", "демон")),
    "magic": ("Магия", ("magic", "магия", "волшебство")),
    "vampires": ("Вампиры", ("vampires", "вампиры", "вампир")),
    "yaoi": ("Яой", ("yaoi", "яой", "юри-яой")),
    "yuri": ("Юри", ("yuri", "юри")),
    "adult": ("Для взрослых", ("adult", "для взрослых", "взрослый", "18+")),
    "gender-bender": (
        "Смена пола",
        ("gender-bender", "gender_bender", "смена пола", "гендерная интрига"),
    ),
    "cooking": ("Кулинария", ("cooking", "кулинария", "еда")),
    "medical": ("Медицина", ("medical", "медицина")),
    "police": ("Полиция", ("police", "полиция")),
    "game": ("Игры", ("game", "games", "игры", "игра", "видеоигры")),
    "time-travel": (
        "Путешествие во времени",
        ("time-travel", "time_travel", "путешествие во времени", "попаданцы"),
    ),
    "tragedy": ("Трагедия", ("tragedy", "трагедия")),
    "crime": ("Преступление", ("crime", "преступление", "криминал")),
    "survival": ("Выживание", ("survival", "выживание")),
    "zombie": ("Зомби", ("zombie", "зомби")),
    "space": ("Космос", ("space", "космос", "космическая фантастика")),
    "samurai": ("Самураи", ("samurai", "самураи", "самурай")),
    "ninja": ("Ниндзя", ("ninja", "ниндзя")),
    "gore": ("Жестокость", ("gore", "жестокость", "расчлененка")),
    "smut": ("Смат", ("smut", "смат", "эротика")),
    "webtoon": ("Вебтун", ("webtoon", "вебтун")),
    "manhwa": ("Манхва", ("manhwa", "манхва")),
    "manhua": ("Маньхуа", ("manhua", "маньхуа")),
    "award-winning": (
        "Удостоено наград",
        ("award-winning", "award_winning", "удостоено наград"),
    ),
    "villainess": ("Злодейка", ("villainess", "злодейка")),
    "reverse-harem": ("Обратный гарем", ("reverse-harem", "reverse_harem", "обратный гарем")),
    "shoujo-ai": ("Сёдзё-ай", ("shoujo-ai", "shoujo_ai", "седзе-ай")),
    "shounen-ai": ("Сёнэн-ай", ("shounen-ai", "shounen_ai", "сенен-ай")),
}

GENRE_ALIASES: dict[str, str] = {
    alias: slug for slug, (_, aliases) in _GENRE_GROUPS.items() for alias in aliases
}
GENRE_LABELS: dict[str, str] = {slug: label for slug, (label, _) in _GENRE_GROUPS.items()}
GENRE_LABELS.update({alias: label for slug, (label, aliases) in _GENRE_GROUPS.items() for alias in aliases})


def normalize_text(value: object | None) -> str:
    """Case/space/``ё``-insensitive key used by status and genre filters."""

    if value is None:
        return ""
    text = str(value).strip().casefold().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;")


def status_key(value: object | None) -> str | None:
    """Map English enum values and Russian source labels to one canonical key."""

    text = normalize_text(value)
    if not text:
        return None
    return STATUS_ALIASES.get(text, text)


def genre_key(value: object | None) -> str:
    text = normalize_text(value)
    # ``|`` is the delimiter of the stored search key.
    text = re.sub(r"\s+", " ", text.replace("|", " ")).strip()
    return GENRE_ALIASES.get(text, text)


def canonical_genre(value: object | None) -> str | None:
    """Return the canonical English slug for a raw genre label."""

    key = genre_key(value)
    return key or None


def genre_label(value: object | None) -> str:
    """Return the human label (Russian where available) for a genre slug/label."""

    key = genre_key(value)
    if not key:
        return ""
    return GENRE_LABELS.get(key, str(value or "").strip())


def genre_slugs(values: object | None) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return []
    return sorted({key for key in (canonical_genre(item) for item in values) if key})


def genres_key(values: object | None) -> str:
    """Build the delimiter-wrapped, lower-case key used for genre filtering.

    Genres are stored as the raw labels supplied by a source but indexed by
    canonical English slug.  This keeps UI labels readable while making
    ``genres=horror+fantasy`` work across MangaPoisk and MangaLib.
    """

    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return ""
    keys = sorted({genre_key(item) for item in values if item})
    return f"|{'|'.join(keys)}|" if keys else ""


def parse_genre_filter(value: str | None) -> list[str]:
    """Parse ``horror+fantasy``, ``horror,fantasy`` or repeated words."""

    if not value:
        return []
    parts = re.split(r"[+,]+|\s+", value.strip())
    keys = [canonical_genre(part) for part in parts if part]
    return list(dict.fromkeys(key for key in keys if key))
