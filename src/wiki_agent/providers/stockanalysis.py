from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from .. import parser
from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter
from .xml import parse_sitemap_entries

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class StockAnalysisAdapter(GenericHtmlAdapter):
    name = "stockanalysis"
    protected_domains = frozenset({"stockanalysis.com"})
    hosts = frozenset({"stockanalysis.com", "www.stockanalysis.com"})
    root_xpaths = ("//main", "//*[@role='main']", "//*[@id='content']", "//body")
    allowed_path_prefixes = (
        "/sitemaps/",
        "/stocks/",
        "/etf/",
        "/quote/",
        "/markets/",
        "/news/",
        "/ipos/",
        "/list/",
        "/industries/",
        "/analysts/",
        "/actions/",
        "/private/",
        "/help/",
        "/trending/",
    )
    allowed_exact_paths = frozenset(
        {
            "/",
            "/sitemap.xml",
            "/sitemap.xml/",
            "/about/",
            "/data-sources/",
            "/terms-of-use/",
            "/privacy-policy/",
            "/advertising-disclosure/",
        }
    )
    blocked_path_prefixes = (
        "/e/",
        "/p/",
        "/api/",
        "/search/",
        "/symbol-lookup/",
        "/login/",
        "/create-account/",
        "/watchlist/",
        "/pro/",
        "/subscribe/",
        "/support/",
        "/contact/",
        "/app/",
        "/stocks/screener/",
        "/stocks/compare/",
        "/etf/screener/",
        "/etf/compare/",
        "/tools/",
    )

    def path_allowed(self, path: str) -> bool:
        normalized = path if path == "/" else f"/{path.strip('/')}/"

        def matches(prefix: str) -> bool:
            return normalized == prefix or normalized.startswith(prefix)

        return (
            normalized in self.allowed_exact_paths
            or any(matches(prefix) for prefix in self.allowed_path_prefixes)
        ) and not any(matches(prefix) for prefix in self.blocked_path_prefixes)

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        if parsed.query:
            raise WikiAgentError(
                "invalid_request",
                "query URLs are blocked by the stockanalysis adapter",
            )
        if parsed.hostname == "www.stockanalysis.com":
            value = urllib.parse.urlunsplit(
                (parsed.scheme, "stockanalysis.com", parsed.path, "", "")
            )
        return super().validate_url(value)

    def robots_url(self, url: str) -> str:
        return "https://stockanalysis.com/robots.txt"

    def accepts_content_type(self, content_type: str | None) -> bool:
        return (
            super().accepts_content_type(content_type)
            or bool(content_type and "xml" in content_type.lower())
        )

    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml"
        }

    def is_sitemap(self, fetch: FetchResult) -> bool:
        path = urllib.parse.urlsplit(fetch.url).path
        return (
            path == "/sitemap.xml" or path.startswith("/sitemaps/")
        ) and (
            fetch.body.lstrip().startswith(b"<?xml")
            or bool(fetch.content_type and "xml" in fetch.content_type.lower())
        )

    def sitemap_entries(self, fetch: FetchResult) -> list[dict[str, str]]:
        return parse_sitemap_entries(
            fetch.body,
            lambda value: self.normalize_link(value, fetch.url),
            "StockAnalysis sitemap",
        )

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path
        if path == "/sitemap.xml" or path.startswith("/sitemaps/"):
            return "listing"
        if path.endswith("/history/"):
            return "listing"
        if path in {
            "/",
            "/stocks/",
            "/etf/",
            "/markets/",
            "/news/",
            "/ipos/",
            "/list/",
            "/industries/",
            "/analysts/",
            "/actions/",
            "/private/",
            "/help/",
        }:
            return "index"
        return "article"

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if not self.is_sitemap(fetch):
            return super().traverse(fetch, max_links, **options)
        entries = self.sitemap_entries(fetch)
        query = options.get("query")
        offset = options.get("offset", 0)
        page_types = set(options.get("page_types") or [])
        namespaces = {
            value.casefold().replace(" ", "_")
            for value in options.get("namespaces") or []
        }
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        for entry in entries:
            target_type = self.page_type(entry["href"])
            path = urllib.parse.unquote(urllib.parse.urlsplit(entry["href"]).path)
            text = path.strip("/").replace("/", " ").replace("-", " ") or "StockAnalysis"
            context = f"Last modified: {entry['lastmod']}" if entry["lastmod"] else ""
            if page_types and target_type not in page_types:
                continue
            if namespaces and self.name not in namespaces:
                continue
            if normalized_query and normalized_query not in (
                f"{text} {entry['href']} {context}".casefold()
            ):
                continue
            matches.append(
                {
                    "href": entry["href"],
                    "text": text,
                    "context": context,
                    "page_type": target_type,
                    "namespace": self.name,
                }
            )
        page = matches[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": "StockAnalysis Sitemap",
            "fetched_at": fetch.fetched_at,
            "links": page,
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "listing",
                    "link_count": len(page),
                    "offset": offset,
                    "next_offset": (
                        offset + len(page)
                        if offset + max_links < len(matches)
                        else None
                    ),
                    "filters": {
                        "query": query,
                        "page_types": list(page_types) or None,
                        "namespaces": list(namespaces) or None,
                    },
                },
            ),
        }

    def skim(
        self,
        fetch: FetchResult,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        if self.is_sitemap(fetch):
            entries = self.sitemap_entries(fetch)
            include_entries = selected_sections is None or "entries" in selected_sections
            return {
                "url": fetch.url,
                "title": "StockAnalysis Sitemap",
                "fetched_at": fetch.fetched_at,
                "infobox": {"image": None, "fields": []},
                "lead": f"StockAnalysis sitemap containing {len(entries)} entries.",
                "sections": [
                    {
                        "id": "entries",
                        "heading": "Entries",
                        "summary": f"First {min(len(entries), max_links_per_section)} entries.",
                        "link_sentences": [
                            {
                                "href": entry["href"],
                                "text": entry["href"],
                                "sentence": entry["lastmod"] or entry["href"],
                            }
                            for entry in entries[:max_links_per_section]
                        ],
                    }
                ] if include_entries else [],
                "see_also": [],
                "categories": [],
                "tables": [],
                "meta": self.result_meta(
                    fetch,
                    {
                        "page_type": "listing",
                        "word_count": 0,
                        "total_sections": 1,
                        "sections_truncated": False,
                        "tables_truncated": False,
                        "reliability_hint": "high",
                    },
                ),
            }
        result = super().skim(
            fetch,
            selected_sections=selected_sections,
            max_links_per_section=max_links_per_section,
        )
        _, root = self.parse(fetch)
        tables, tables_truncated = parser.extract_tables(root)
        result["tables"] = tables
        result["meta"]["tables_truncated"] = tables_truncated
        return result

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        if self.is_sitemap(fetch):
            entries = self.sitemap_entries(fetch)
            text = "\n".join(
                f"{entry['href']}\t{entry['lastmod']}".rstrip()
                for entry in entries
            )
            skim = self.skim(
                fetch,
                selected_sections=None,
                max_links_per_section=10,
            )
            return {
                "url": fetch.url,
                "title": "StockAnalysis Sitemap",
                "fetched_at": fetch.fetched_at,
                "text": text,
                "html": None,
                "skim": skim,
                "tables": [],
                "meta": self.result_meta(
                    fetch,
                    {
                        "page_type": "listing",
                        "word_count": len(text.split()),
                        "sections_returned": 1,
                    },
                ),
            }
        result = super().read(fetch, output_format=output_format)
        tables = result["skim"].pop("tables")
        result["tables"] = tables
        return result
