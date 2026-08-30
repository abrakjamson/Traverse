from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .cache import Cache
from .config import Config
from .errors import WikiAgentError
from .fetcher import WikipediaFetcher
from . import parser


def create_mcp_server(config: Config) -> FastMCP:
    mcp = FastMCP(
        "PurePath",
        instructions=(
            "Browse English Wikipedia politely. Use traverse for link discovery, "
            "skim for section-level understanding, and read for full page content."
        ),
    )
    cache = Cache(config.cache_path)
    fetcher = WikipediaFetcher(config, cache)
    fetcher.initialize()

    def tool_error(exc: WikiAgentError) -> ValueError:
        return ValueError(f"{exc.code}: {exc.message}")

    @mcp.tool()
    def traverse(
        url: str,
        max_links: int = 50,
        cache_only: bool = False,
        query: str | None = None,
        page_types: list[str] | None = None,
        namespaces: list[str] | None = None,
        offset: int = 0,
        context_max_chars: int = 240,
    ) -> dict[str, Any]:
        """Discover filtered, paginated links from a Wikipedia page."""
        if not 1 <= max_links <= 200:
            raise ValueError("max_links must be from 1 to 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 0 <= context_max_chars <= 2000:
            raise ValueError("context_max_chars must be from 0 to 2000")
        valid_page_types = {"article", "portal", "category", "other"}
        if page_types and not set(page_types).issubset(valid_page_types):
            raise ValueError("page_types contains an unsupported value")
        try:
            fetched = fetcher.fetch(url, cache_only=cache_only)
            return parser.traverse(
                fetched,
                max_links,
                query=query,
                page_types=page_types,
                namespaces=namespaces,
                offset=offset,
                context_max_chars=context_max_chars,
            )
        except WikiAgentError as exc:
            raise tool_error(exc) from exc

    @mcp.tool()
    def skim(
        url: str,
        sections: list[str] | None = None,
        max_links_per_section: int = 10,
        cache_ttl_override: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve a concise semantic overview, infobox, sections, and link sentences."""
        if not 0 <= max_links_per_section <= 100:
            raise ValueError("max_links_per_section must be from 0 to 100")
        if cache_ttl_override is not None:
            if not config.dev:
                raise ValueError("cache_ttl_override is only available in dev mode")
            if cache_ttl_override < 0:
                raise ValueError("cache_ttl_override must be non-negative")
        try:
            fetched = fetcher.fetch(url, ttl_seconds=cache_ttl_override)
            return parser.skim(
                fetched,
                selected_sections=sections,
                max_links_per_section=max_links_per_section,
            )
        except WikiAgentError as exc:
            raise tool_error(exc) from exc

    @mcp.tool()
    def read(url: str, format: str = "plain") -> dict[str, Any]:
        """Retrieve full simplified text or sanitized HTML from a Wikipedia page."""
        if format not in {"plain", "html"}:
            raise ValueError("format must be plain or html")
        try:
            fetched = fetcher.fetch(url)
            return parser.read(fetched, output_format=format)
        except WikiAgentError as exc:
            raise tool_error(exc) from exc

    @mcp.tool()
    def health() -> dict[str, Any]:
        """Return crawler liveness and robots/politeness state."""
        return {
            "status": "ok",
            "robots_checked_at": fetcher.robots_checked_at,
            "crawl_delay_seconds": fetcher.crawl_delay_seconds,
        }

    return mcp


def run_mcp_server(config: Config) -> None:
    create_mcp_server(config).run(transport="stdio")
