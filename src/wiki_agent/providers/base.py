from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class SiteAdapter(ABC):
    name: str

    @abstractmethod
    def matches(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_url(self, value: object) -> str:
        raise NotImplementedError

    @abstractmethod
    def robots_url(self, url: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def skim(
        self,
        fetch: FetchResult,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        raise NotImplementedError
