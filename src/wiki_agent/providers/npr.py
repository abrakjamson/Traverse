from __future__ import annotations

import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, clean_text, element_text
from .xml import parse_sitemap_entries

if TYPE_CHECKING:
    from ..fetcher import FetchResult


class NprAdapter(GenericHtmlAdapter):
    name = "npr"
    protected_domains = frozenset({"npr.org"})
    hosts = frozenset({"npr.org", "www.npr.org"})
    root_xpaths = (
        "//main",
        "//*[@role='main']",
        "//article",
        "//*[@id='content']",
        "//body",
    )
    def path_allowed(self, path: str) -> bool:
        lowered = path.casefold()
        return (
            lowered == "/"
            or lowered.startswith("/sections/")
            or lowered.startswith("/live-updates/")
            or bool(re.match(r"^/\d{4}/\d{2}/\d{2}/", lowered))
        )

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        if parsed.query:
            raise WikiAgentError(
                "invalid_request",
                "query URLs are blocked by the npr adapter",
            )
        if parsed.hostname == "npr.org":
            value = urllib.parse.urlunsplit(
                (parsed.scheme, "www.npr.org", parsed.path, "", "")
            )
        return super().validate_url(value)

    def robots_url(self, url: str) -> str:
        return "https://www.npr.org/robots.txt"

    def discovery_link(self, value: str | None, base_url: str) -> str | None:
        return self.normalize_link(value, base_url)

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
            path.startswith("/live-updates/sitemap")
            and (
                fetch.body.lstrip().startswith(b"<?xml")
                or bool(fetch.content_type and "xml" in fetch.content_type.lower())
            )
        )

    def sitemap_entries(self, fetch: FetchResult) -> list[dict[str, str]]:
        return parse_sitemap_entries(
            fetch.body,
            lambda value: self.normalize_link(value, fetch.url),
            "NPR sitemap",
        )

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path
        if path.startswith("/live-updates/sitemap") and path.endswith(".xml"):
            return "listing"
        if re.match(r"^/\d{4}/\d{2}/\d{2}/", path):
            return "article"
        if path.startswith("/live-updates/"):
            return "article"
        if path in {"", "/"}:
            return "index"
        return "listing"

    def custom_lead(self, root: etree._Element) -> str | None:
        for paragraph in root.xpath(".//p"):
            text = element_text(paragraph)
            lowered = text.casefold()
            if len(text) < 80:
                continue
            if "hide caption" in lowered or "toggle caption" in lowered:
                continue
            return text
        return None

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
                types = item.get("@type")
                if isinstance(types, str):
                    type_names = {types}
                elif isinstance(types, list):
                    type_names = {
                        value for value in types if isinstance(value, str)
                    }
                else:
                    type_names = set()
                if not type_names & {"Article", "NewsArticle"}:
                    continue
                fields: list[dict[str, str]] = []
                authors = item.get("author")
                names = []
                for author in authors if isinstance(authors, list) else [authors]:
                    if isinstance(author, dict) and isinstance(author.get("name"), str):
                        names.append(clean_text(author["name"]))
                if names:
                    fields.append({"key": "Author", "value": ", ".join(names)})
                for key, label in (
                    ("datePublished", "Published"),
                    ("dateModified", "Updated"),
                ):
                    if isinstance(item.get(key), str):
                        fields.append({"key": label, "value": clean_text(item[key])})
                image = item.get("image")
                if isinstance(image, dict):
                    image = image.get("url")
                return {
                    "image": image if isinstance(image, str) else None,
                    "fields": fields,
                }
        return {"image": None, "fields": []}

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if not self.is_sitemap(fetch):
            return super().traverse(fetch, max_links, **options)
        entries = self.sitemap_entries(fetch)
        query = options.get("query")
        offset = options.get("offset", 0)
        page_types = set(options.get("page_types") or [])
        namespaces = set(options.get("namespaces") or [])
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        for entry in entries:
            target_type = self.page_type(entry["href"])
            text = urllib.parse.unquote(
                urllib.parse.urlsplit(entry["href"]).path.rstrip("/").rsplit("/", 1)[-1]
            ).replace("-", " ")
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
                    "text": text or entry["href"],
                    "context": context,
                    "page_type": target_type,
                    "namespace": self.name,
                }
            )
        page = matches[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": "NPR Live Updates Sitemap",
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
        if not self.is_sitemap(fetch):
            return super().skim(
                fetch,
                selected_sections=selected_sections,
                max_links_per_section=max_links_per_section,
            )
        entries = self.sitemap_entries(fetch)
        include_entries = selected_sections is None or "entries" in selected_sections
        return {
            "url": fetch.url,
            "title": "NPR Live Updates Sitemap",
            "fetched_at": fetch.fetched_at,
            "infobox": {"image": None, "fields": []},
            "lead": f"NPR live-update sitemap containing {len(entries)} entries.",
            "sections": [
                {
                    "id": "entries",
                    "heading": "Entries",
                    "summary": f"First {min(len(entries), 10)} entries.",
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

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        if not self.is_sitemap(fetch):
            return super().read(fetch, output_format=output_format)
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
            "title": "NPR Live Updates Sitemap",
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
