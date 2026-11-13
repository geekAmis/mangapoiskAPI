from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProfileEventKind = Literal["chapter_read", "title_finished", "achievement"]


class RankOut(BaseModel):
    """A public rank/title.  Ranks are deterministic level bands."""

    code: str
    label: str
    min_level: int


class ProfilePrivacyOut(BaseModel):
    """Privacy switches safe to expose: they describe visibility, not secrets."""

    is_private: bool = False
    show_stats: bool = True
    show_events: bool = True
    show_achievements: bool = True
    indexable: bool = True


class AchievementOut(BaseModel):
    code: str
    title: str
    description: str
    icon: str = "star"
    unlocked: bool = False
    # Owners see the exact moment; guests only get the calendar date so the
    # public card never exposes precise reading timestamps.
    unlocked_at: datetime | None = None
    unlocked_on: date | None = None
    progress: int = 0
    target: int = 0


class ProfileStatsOut(BaseModel):
    chapters_read: int = 0
    titles_read: int = 0
    finished_titles: int = 0
    reading_days: int = 0
    current_streak: int = 0
    longest_streak: int = 0


class GenreCountOut(BaseModel):
    genre: str
    count: int


class ProfileEventOut(BaseModel):
    id: UUID
    kind: ProfileEventKind
    title: str
    subtitle: str | None = None
    manga_id: UUID | None = None
    chapter_id: UUID | None = None
    poster_url: str | None = None
    achievement_code: str | None = None
    # Guests receive the calendar date only; the exact timestamp is reserved
    # for the owner (and is never part of the public profile response).
    occurred_on: date
    created_at: datetime | None = None


class PublicProfileOut(BaseModel):
    """Public profile card.

    Deliberately contains no email, role, internal user id, reporter id, IP or
    user agent.  Hidden sections are represented by ``*_hidden`` flags instead
    of leaking aggregate values.
    """

    username: str
    display_name: str
    bio: str = ""
    joined_at: date
    level: int = 1
    xp: int = 0
    xp_into_level: int = 0
    xp_for_next_level: int = 50
    level_progress: float = 0.0
    rank: RankOut
    next_rank: RankOut | None = None
    avatar_initials: str = ""
    privacy: ProfilePrivacyOut = Field(default_factory=ProfilePrivacyOut)
    indexable: bool = False
    is_owner: bool = False
    stats: ProfileStatsOut | None = None
    favorite_genres: list[GenreCountOut] = Field(default_factory=list)
    achievements: list[AchievementOut] = Field(default_factory=list)
    achievements_unlocked: int = 0
    achievements_total: int = 0
    achievements_hidden: bool = False
    events: list[ProfileEventOut] = Field(default_factory=list)
    events_hidden: bool = False


class MyProfileOut(PublicProfileOut):
    """Owner view: everything is visible and locked achievements are included."""


class ProfileUpdate(BaseModel):
    """Partial profile update.  Omitted fields are left unchanged."""

    display_name: str | None = Field(default=None, min_length=1, max_length=48)
    username: str | None = Field(default=None, min_length=3, max_length=24)
    bio: str | None = Field(default=None, max_length=280)
    is_private: bool | None = None
    show_stats: bool | None = None
    show_events: bool | None = None
    show_achievements: bool | None = None
    indexable: bool | None = None


class ProfileReportIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProfileReportOut(BaseModel):
    id: UUID
    status: str = "open"
    created_at: datetime
    message: str = "Жалоба отправлена на проверку"


class AdminProfileReportOut(BaseModel):
    id: UUID
    target_username: str
    target_display_name: str
    reporter_username: str
    reason: str
    status: str
    # False when the target hid the card from guests; moderators still see the
    # report metadata but the public link would 404.
    target_visible: bool = True
    created_at: datetime
    resolved_at: datetime | None = None


class ProfileReportResolveIn(BaseModel):
    status: Literal["resolved", "dismissed"] = "resolved"
