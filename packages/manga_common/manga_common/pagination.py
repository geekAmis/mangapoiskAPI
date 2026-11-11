from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PageParams:
    page: int = 1
    limit: int = 24

    def __post_init__(self) -> None:
        self.page = max(1, self.page)
        self.limit = min(max(1, self.limit), 100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

    def has_next(self, total: int) -> bool:
        return self.offset + self.limit < total
