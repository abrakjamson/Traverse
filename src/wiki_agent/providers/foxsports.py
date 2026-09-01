from __future__ import annotations

import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from .. import parser
from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, clean_text, element_text
from .xml import parse_sitemap_entries

if TYPE_CHECKING:
    from ..fetcher import FetchResult


SPORT_HUBS = {
    "/nfl": "NFL",
    "/mlb": "MLB",
    "/nba": "NBA",
    "/nhl": "NHL",
    "/wnba": "WNBA",
    "/college-football": "College Football",
    "/college-basketball": "College Basketball",
    "/soccer/mls": "MLS",
    "/soccer/premier-league": "Premier League",
    "/soccer/champions-league": "UEFA Champions League",
    "/soccer/fifa-world-cup": "FIFA World Cup",
    "/nascar": "NASCAR",
    "/golf": "Golf",
    "/ufc": "UFC",
    "/tennis": "Tennis",
}

TEAM_COMPETITIONS = frozenset(
    {
        "/nfl",
        "/mlb",
        "/nba",
        "/nhl",
        "/wnba",
        "/college-football",
        "/college-basketball",
        "/soccer/mls",
        "/soccer/premier-league",
        "/soccer/champions-league",
        "/soccer/fifa-world-cup",
    }
)

SITEMAP_TYPES = frozenset(
    {
        "articles",
        "auto",
        "baseball",
        "basketball",
        "bowling",
        "boxing",
        "dogshow",
        "fastchanging",
        "fighting",
        "football",
        "golf",
        "hockey",
        "liveblogs",
        "mma",
        "news",
        "olympics",
        "other",
        "pages",
        "personalities",
        "rugby",
        "shows",
        "soccer",
        "tennis",
        "topic",
        "videos",
    }
)


class FoxSportsAdapter(GenericHtmlAdapter):
    name = "foxsports"
    protected_domains = frozenset({"foxsports.com"})
    hosts = frozenset({"foxsports.com", "www.foxsports.com"})
    allowed_query_keys = frozenset(
        {"type", "page", "season", "seasonType", "week", "date"}
    )
    root_xpaths = (
        "//*[@id='main']",
        "//main",
        "//*[@role='main']",
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' fscom-main-content ')]",
        "//body",
    )
    blocked_path_prefixes = (
        "/maintenance/",
        "/foxbox/",
        "/xid",
        "/search/",
        "/account/",
        "/login/",
        "/register/",
        "/subscribe/",
        "/live/",
        "/watch/",
        "/betting/",
    )

    def matches(self, url: str) -> bool:
        hostname = (urllib.parse.urlsplit(url).hostname or "").rstrip(".").casefold()
        return hostname == "foxsports.com" or hostname.endswith(".foxsports.com")

    def path_allowed(self, path: str) -> bool:
        lowered = path.casefold()
        if any(
            lowered == prefix.rstrip("/") or lowered.startswith(prefix)
            for prefix in self.blocked_path_prefixes
        ):
            return False
        return lowered == "/" or lowered == "/sitemap.xml" or lowered.startswith(
            (
                "/nfl",
                "/mlb",
                "/nba",
                "/nhl",
                "/wnba",
                "/college-football",
                "/college-basketball",
                "/soccer",
                "/nascar",
                "/golf",
                "/ufc",
                "/tennis",
                "/stories",
                "/personalities",
                "/shows",
                "/video",
                "/sitemap.xml",
            )
        )

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        if parsed.username or parsed.password or parsed.port:
            raise WikiAgentError("invalid_request", "url must not contain credentials or a port")
        path = urllib.parse.unquote(parsed.path or "/")
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        normalized_path = path.rstrip("/").casefold()
        allowed_keys: set[str] = set()
        if normalized_path == "/sitemap.xml":
            allowed_keys = {"type", "page"}
        elif normalized_path.endswith(("/schedule", "/standings")):
            allowed_keys = {"season", "seasonType", "week"}
        elif normalized_path.endswith("/scores"):
            allowed_keys = {"date"}
        if pairs and any(key not in allowed_keys for key, _ in pairs):
            raise WikiAgentError(
                "invalid_request",
                "query contains parameters unsupported by the foxsports adapter",
            )
        values = dict(pairs)
        if len(values) != len(pairs):
            raise WikiAgentError(
                "invalid_request",
                "Fox Sports query parameters must not be repeated",
            )
        if "type" in values and values["type"] not in SITEMAP_TYPES:
            raise WikiAgentError("invalid_request", "unsupported Fox Sports sitemap type")
        if "page" in values and not re.fullmatch(r"\d{1,4}", values["page"]):
            raise WikiAgentError("invalid_request", "Fox Sports sitemap page must be numeric")
        if "season" in values and not re.fullmatch(r"\d{4}", values["season"]):
            raise WikiAgentError("invalid_request", "Fox Sports season must be a four-digit year")
        if "seasonType" in values and values["seasonType"] not in {"pre", "reg", "post"}:
            raise WikiAgentError(
                "invalid_request",
                "Fox Sports seasonType must be pre, reg, or post",
            )
        if "week" in values and not re.fullmatch(r"\d{1,2}", values["week"]):
            raise WikiAgentError("invalid_request", "Fox Sports week must be numeric")
        if "date" in values and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["date"]):
            raise WikiAgentError("invalid_request", "Fox Sports date must use YYYY-MM-DD")
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if hostname not in self.hosts:
            raise WikiAgentError(
                "invalid_request",
                "only the public foxsports.com website is supported",
            )
        normalized = urllib.parse.urlunsplit(
            (
                "https",
                "www.foxsports.com",
                parsed.path or "/",
                urllib.parse.urlencode(pairs),
                "",
            )
        )
        return super().validate_url(normalized)

    def normalize_link(self, value: str | None, base_url: str) -> str | None:
        normalized = super().normalize_link(value, base_url)
        if normalized:
            return normalized
        if not value:
            return None
        absolute = urllib.parse.urljoin(base_url, value)
        parsed = urllib.parse.urlsplit(absolute)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if hostname != "foxsports.com" and not hostname.endswith(".foxsports.com"):
            return None
        without_query = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        try:
            return self.validate_url(without_query)
        except WikiAgentError:
            return None

    def robots_url(self, url: str) -> str:
        return "https://www.foxsports.com/robots.txt"

    def accepts_content_type(self, content_type: str | None) -> bool:
        return (
            super().accepts_content_type(content_type)
            or bool(content_type and "xml" in content_type.lower())
        )

    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml"
        }

    def title(self, document: html.HtmlElement, root: etree._Element) -> str:
        for xpath in (
            "//meta[@property='og:title']/@content",
            "//meta[@name='twitter:title']/@content",
        ):
            values = document.xpath(xpath)
            if values and (title := clean_text(values[0])):
                return title
        return super().title(document, root)

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path.rstrip("/").casefold()
        if path == "/sitemap.xml":
            return "listing"
        if path in SPORT_HUBS or path in {"", "/"}:
            return "index"
        if path.endswith(("/scores", "/standings", "/schedule", "/teams", "/stats")):
            return "listing"
        if path.startswith(("/stories/", "/video/")):
            return "article"
        return "article"

    def metadata(
        self,
        document: html.HtmlElement,
        root: etree._Element,
    ) -> dict[str, Any]:
        for script in document.xpath("//script[@type='application/ld+json']"):
            try:
                payload = json.loads(script.text or "")
            except json.JSONDecodeError:
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type")
                if item_type not in {"Article", "NewsArticle"}:
                    continue
                fields: list[dict[str, str]] = []
                authors = item.get("author")
                if not isinstance(authors, list):
                    authors = [authors]
                names = [
                    author.get("name")
                    for author in authors
                    if isinstance(author, dict) and isinstance(author.get("name"), str)
                ]
                if names:
                    fields.append({"key": "Author", "value": ", ".join(names)})
                for key, label in (
                    ("datePublished", "Published"),
                    ("dateModified", "Updated"),
                ):
                    if isinstance(item.get(key), str):
                        fields.append({"key": label, "value": item[key]})
                image = item.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                if isinstance(image, dict):
                    image = image.get("url")
                return {
                    "image": image if isinstance(image, str) else None,
                    "fields": fields,
                }
        return {"image": None, "fields": []}

    def is_sitemap(self, fetch: FetchResult) -> bool:
        return (
            urllib.parse.urlsplit(fetch.url).path == "/sitemap.xml"
            and (
                fetch.body.lstrip().startswith(b"<?xml")
                or bool(fetch.content_type and "xml" in fetch.content_type.lower())
            )
        )

    def sitemap_entries(self, fetch: FetchResult) -> list[dict[str, str]]:
        return parse_sitemap_entries(
            fetch.body,
            lambda value: self.normalize_link(value, fetch.url),
            "Fox Sports sitemap",
        )

    def _synthetic_links(self, url: str) -> list[dict[str, str]]:
        path = urllib.parse.urlsplit(url).path.rstrip("/").casefold()
        if path in {"", "/"}:
            return [
                {
                    "href": f"https://www.foxsports.com{hub}",
                    "text": title,
                    "context": f"{title} league hub",
                    "page_type": "index",
                    "namespace": self.name,
                }
                for hub, title in SPORT_HUBS.items()
            ]
        if path not in TEAM_COMPETITIONS:
            return []
        title = SPORT_HUBS[path]
        return [
            {
                "href": f"https://www.foxsports.com{path}/{section}",
                "text": label,
                "context": f"{title} {label.casefold()}",
                "page_type": "listing" if section != "news" else "article",
                "namespace": self.name,
            }
            for section, label in (
                ("scores", "Scores"),
                ("standings", "Standings"),
                ("schedule", "Schedule"),
                ("teams", "Teams"),
                ("stats", "Stats"),
                ("news", "News"),
            )
        ]

    def _traverse_sitemap(
        self,
        fetch: FetchResult,
        max_links: int,
        **options: Any,
    ) -> dict[str, Any]:
        entries = self.sitemap_entries(fetch)
        links = [
            {
                "href": entry["href"],
                "text": urllib.parse.unquote(
                    urllib.parse.urlsplit(entry["href"]).path.strip("/")
                ).replace("-", " ") or "Fox Sports",
                "context": f"Last modified: {entry['lastmod']}" if entry["lastmod"] else "",
                "page_type": self.page_type(entry["href"]),
                "namespace": self.name,
            }
            for entry in entries
        ]
        return self._filtered_traverse_result(fetch, links, max_links, **options)

    def _filtered_traverse_result(
        self,
        fetch: FetchResult,
        links: list[dict[str, str]],
        max_links: int,
        **options: Any,
    ) -> dict[str, Any]:
        query = options.get("query")
        page_types = set(options.get("page_types") or [])
        namespaces = {
            value.casefold().replace(" ", "_")
            for value in options.get("namespaces") or []
        }
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in links:
            if link["href"] in seen:
                continue
            seen.add(link["href"])
            if page_types and link["page_type"] not in page_types:
                continue
            if namespaces and link["namespace"] not in namespaces:
                continue
            if normalized_query and normalized_query not in (
                f"{link['text']} {link['href']} {link['context']}".casefold()
            ):
                continue
            matches.append(link)
        offset = options.get("offset", 0)
        page = matches[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": "Fox Sports Sitemap" if self.is_sitemap(fetch) else self._page_title(fetch),
            "fetched_at": fetch.fetched_at,
            "links": page,
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": self.page_type(fetch.url),
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

    def _page_title(self, fetch: FetchResult) -> str:
        document, root = self.parse(fetch)
        return self.title(document, root)

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if self.is_sitemap(fetch):
            return self._traverse_sitemap(fetch, max_links, **options)
        actual = super().traverse(
            fetch,
            5_000,
            query=None,
            page_types=None,
            namespaces=None,
            offset=0,
            context_max_chars=options.get("context_max_chars", 240),
        )
        return self._filtered_traverse_result(
            fetch,
            self._synthetic_links(fetch.url) + actual["links"],
            max_links,
            **options,
        )

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
                "title": "Fox Sports Sitemap",
                "fetched_at": fetch.fetched_at,
                "infobox": {"image": None, "fields": []},
                "lead": f"Fox Sports sitemap containing {len(entries)} entries.",
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
        if not result["lead"]:
            result["lead"] = (
                f"FOX Sports page for {result['title']}, with navigation, "
                "current sports data, and related coverage."
            )
        return result

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        if self.is_sitemap(fetch):
            entries = self.sitemap_entries(fetch)
            text = "\n".join(
                f"{entry['href']}\t{entry['lastmod']}".rstrip()
                for entry in entries
            )
            skim = self.skim(fetch, selected_sections=None, max_links_per_section=10)
            return {
                "url": fetch.url,
                "title": "Fox Sports Sitemap",
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
