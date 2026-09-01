from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from .. import parser
from ..errors import WikiAgentError
from ..urls import ALLOWED_NAMESPACES, BLOCKED_NAMESPACES, namespace_for_title
from .base import SiteAdapter

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class WikipediaAdapter(SiteAdapter):
    name = "wikipedia"

    def __init__(self, base_url: str = "https://en.wikipedia.org"):
        self.base_url = base_url.rstrip("/")
        self._origin = urllib.parse.urlsplit(self.base_url)
        self.protected_domains = frozenset({self._origin.hostname or ""})

    def matches(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme == self._origin.scheme and parsed.hostname == self._origin.hostname

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != self._origin.scheme or parsed.hostname != self._origin.hostname:
            raise WikiAgentError("invalid_request", f"url must use {self.base_url}")
        if parsed.username or parsed.password or parsed.port or parsed.query:
            raise WikiAgentError("invalid_request", "url must not contain credentials, a port, or a query")
        if not parsed.path.startswith("/wiki/"):
            raise WikiAgentError("invalid_request", "only Wikipedia /wiki/* pages are supported")
        raw_path_lower = parsed.path.lower()
        if "%2f" in raw_path_lower or "%5c" in raw_path_lower:
            raise WikiAgentError("invalid_request", "encoded path separators are not allowed")
        decoded_path = urllib.parse.unquote(parsed.path)
        if any(segment == ".." for segment in decoded_path.split("/")):
            raise WikiAgentError("invalid_request", "parent path segments are not allowed")
        title = decoded_path.removeprefix("/wiki/")
        namespace = namespace_for_title(title)
        if not title or namespace in BLOCKED_NAMESPACES or namespace not in ALLOWED_NAMESPACES:
            raise WikiAgentError("invalid_request", f"the {namespace.replace('_', ' ')} namespace is not supported")
        clean_path = urllib.parse.quote(decoded_path, safe="/:()_")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", ""))

    def robots_url(self, url: str) -> str:
        return f"{self.base_url}/robots.txt"

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        return parser.traverse(fetch, max_links, **options)

    def skim(
        self,
        fetch: FetchResult,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        return parser.skim(
            fetch,
            selected_sections=selected_sections,
            max_links_per_section=max_links_per_section,
        )

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        return parser.read(fetch, output_format=output_format)
