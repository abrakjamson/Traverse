from __future__ import annotations

import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from .. import parser
from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, clean_text, element_text

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class WebMdAdapter(GenericHtmlAdapter):
    name = "webmd"
    protected_domains = frozenset({"webmd.com"})
    hosts = frozenset({"webmd.com", "www.webmd.com"})
    allowed_query_keys = frozenset({"pg"})
    root_xpaths = (
        "//*[@id='main-content']",
        "//main",
        "//*[@role='main']",
        "//article",
        "//body",
    )
    blocked_path_prefixes = (
        "/500",
        "/aim/",
        "/api/",
        "/click",
        "/dna",
        "/drugs/2/search",
        "/drugs/reportabuse.aspx",
        "/kapi/",
        "/mm/",
        "/my-library",
        "/pill-identification/search-results",
        "/search/",
        "/share.aspx",
        "/sponsored/",
        "/static/",
        "/story/",
        "/webmd_static_vue/",
    )
    topic_index_path = "/a-to-z-guides/health-topics"

    def path_allowed(self, path: str) -> bool:
        lowered = path.casefold()
        return (
            "/search/search_results/" not in lowered
            and not any(
                lowered == prefix.rstrip("/") or lowered.startswith(prefix)
                for prefix in self.blocked_path_prefixes
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
        if path.rstrip("/").casefold() == self.topic_index_path:
            if len(pairs) > 1 or any(key != "pg" for key, _ in pairs):
                raise WikiAgentError(
                    "invalid_request",
                    "WebMD health topic indexes only support the pg parameter",
                )
            if pairs and not re.fullmatch(r"[a-z]", pairs[0][1].casefold()):
                raise WikiAgentError(
                    "invalid_request",
                    "WebMD health topic pg must be a single letter from a to z",
                )
            query = urllib.parse.urlencode(
                [(key, item.casefold()) for key, item in pairs]
            )
        elif pairs:
            raise WikiAgentError(
                "invalid_request",
                "query URLs are blocked by the webmd adapter",
            )
        else:
            query = ""
        parsed_hostname = (parsed.hostname or "").rstrip(".").casefold()
        hostname = "www.webmd.com" if parsed_hostname == "webmd.com" else parsed_hostname
        normalized = urllib.parse.urlunsplit(
            (parsed.scheme, hostname or "", parsed.path, query, "")
        )
        return super().validate_url(normalized)

    def robots_url(self, url: str) -> str:
        return "https://www.webmd.com/robots.txt"

    def discovery_link(self, value: str | None, base_url: str) -> str | None:
        return self.normalize_link(value, base_url)

    def normalize_link(self, value: str | None, base_url: str) -> str | None:
        if not value or value.startswith(("javascript:", "mailto:", "tel:")):
            return None
        absolute = urllib.parse.urljoin(base_url, value)
        parsed = urllib.parse.urlsplit(absolute)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if hostname not in self.hosts:
            return None
        if (
            urllib.parse.unquote(parsed.path).rstrip("/").casefold()
            != self.topic_index_path
        ):
            absolute = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, "", "")
            )
        try:
            return self.validate_url(absolute)
        except WikiAgentError:
            return None

    def title(self, document: html.HtmlElement, root: etree._Element) -> str:
        for xpath in (
            "//meta[@property='og:title']/@content",
            "//meta[@name='twitter:title']/@content",
        ):
            values = document.xpath(xpath)
            if values and (title := clean_text(values[0])):
                return title
        headings = [
            element_text(node)
            for node in root.xpath(".//h1")
            if "find doctors" not in element_text(node).casefold()
        ]
        if headings:
            return headings[0]
        return super().title(document, root)

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path.rstrip("/").casefold()
        if path == self.topic_index_path:
            return "listing"
        if path.endswith("/default.htm") or path in {
            "",
            "/a-to-z-guides",
            "/a-to-z-guides/default.htm",
        }:
            return "index"
        return "article"

    def custom_lead(self, root: etree._Element) -> str | None:
        for paragraph in root.xpath(".//p"):
            text = element_text(paragraph)
            lowered = text.casefold()
            if len(text) < 70:
                continue
            if any(
                phrase in lowered
                for phrase in (
                    "find doctors",
                    "medically reviewed by",
                    "this tool does not provide medical advice",
                    "advertisement",
                )
            ):
                continue
            return text
        return None

    def metadata(
        self,
        document: html.HtmlElement,
        root: etree._Element,
    ) -> dict[str, Any]:
        fields: list[dict[str, str]] = []
        image: str | None = None
        for script in document.xpath("//script[@type='application/ld+json']"):
            try:
                payload = json.loads(script.text or "")
            except json.JSONDecodeError:
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                graph = item.get("@graph")
                if isinstance(graph, list):
                    candidates.extend(node for node in graph if isinstance(node, dict))
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if not any(
                    value in {"Article", "MedicalWebPage", "NewsArticle"}
                    for value in types
                ):
                    continue
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
                reviewed = item.get("reviewedBy")
                if isinstance(reviewed, dict) and isinstance(reviewed.get("name"), str):
                    fields.append({"key": "Reviewed by", "value": reviewed["name"]})
                for key, label in (
                    ("datePublished", "Published"),
                    ("dateModified", "Updated"),
                    ("lastReviewed", "Last reviewed"),
                ):
                    if isinstance(item.get(key), str):
                        fields.append({"key": label, "value": item[key]})
                value = item.get("image")
                if isinstance(value, list):
                    value = value[0] if value else None
                if isinstance(value, dict):
                    value = value.get("url")
                image = value if isinstance(value, str) else None
                return {"image": image, "fields": fields}
        return {"image": image, "fields": fields}

    def _topic_directory_links(self) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for letter in "abcdefghijklmnopqrstuvwxyz":
            links.append(
                {
                    "href": (
                        f"https://www.webmd.com{self.topic_index_path}?pg={letter}"
                    ),
                    "text": letter.upper(),
                    "context": f"Health topics beginning with {letter.upper()}",
                    "page_type": "listing",
                    "namespace": self.name,
                }
            )
        return links

    def is_topic_index(self, url: str) -> bool:
        return (
            urllib.parse.urlsplit(url).path.rstrip("/").casefold()
            == self.topic_index_path
        )

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if not self.is_topic_index(fetch.url):
            return super().traverse(fetch, max_links, **options)
        actual = super().traverse(
            fetch,
            5_000,
            query=None,
            page_types=None,
            namespaces=None,
            offset=0,
            context_max_chars=options.get("context_max_chars", 240),
        )
        combined = self._topic_directory_links() + actual["links"]
        query = options.get("query")
        page_types = set(options.get("page_types") or [])
        namespaces = {
            value.casefold().replace(" ", "_")
            for value in options.get("namespaces") or []
        }
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in combined:
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
        actual["links"] = page
        actual["meta"].update(
            {
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
            }
        )
        return actual

    def skim(
        self,
        fetch: FetchResult,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        result = super().skim(
            fetch,
            selected_sections=selected_sections,
            max_links_per_section=max_links_per_section,
        )
        _, root = self.parse(fetch)
        tables, tables_truncated = parser.extract_tables(root)
        result["tables"] = tables
        result["meta"]["tables_truncated"] = tables_truncated
        if self.is_topic_index(fetch.url) and not result["lead"]:
            letter = dict(urllib.parse.parse_qsl(
                urllib.parse.urlsplit(fetch.url).query
            )).get("pg", "a").upper()
            result["lead"] = f"WebMD health topics beginning with {letter}."
        return result

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        result = super().read(fetch, output_format=output_format)
        tables = result["skim"].pop("tables")
        result["tables"] = tables
        return result
