from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class SiteAdapter(ABC):
    name: str
    protected_domains: frozenset[str] = frozenset()
    is_fallback = False

    @abstractmethod
    def matches(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_url(self, value: object) -> str:
        raise NotImplementedError

    @abstractmethod
    def robots_url(self, url: str) -> str:
        raise NotImplementedError

    def validate_network_destination(self, url: str) -> tuple[str, ...] | None:
        return None

    def accepts_content_type(self, content_type: str | None) -> bool:
        return content_type is None or "html" in content_type.lower()

    def request_headers(self) -> dict[str, str]:
        return {}

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
