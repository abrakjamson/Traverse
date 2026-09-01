from __future__ import annotations

import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, GenericSection, clean_text, element_text

if TYPE_CHECKING:
    from ..fetcher import FetchResult


SEARCH_QUERY_KEYS = {
    "keyword",
    "q",
    "query",
    "s",
    "search",
    "searchterm",
}


class NerdWalletAdapter(GenericHtmlAdapter):
    name = "nerdwallet"
    protected_domains = frozenset({"nerdwallet.com"})
    hosts = frozenset({"nerdwallet.com", "www.nerdwallet.com"})
    root_xpaths = (
        "//main",
        "//*[@role='main']",
        "//article",
        "//*[@id='content']",
        "//body",
    )
    blocked_path_prefixes = (
        "/search",
        "/api",
        "/wp-json",
        "/creditcarddetailajax",
        "/compareajax",
        "/structured-content-renderer",
        "/ab-taproom-api",
        "/cc-prequal-service",
        "/identity",
        "/redirect",
        "/prequalify",
    )

    def path_allowed(self, path: str) -> bool:
        lowered = path.casefold()
        if any(
            lowered == prefix.rstrip("/") or lowered.startswith(prefix)
            for prefix in self.blocked_path_prefixes
        ):
            return False
        if "/network-links/" in lowered or lowered.endswith("/embed"):
            return False
        if lowered.startswith("/insurance/") and lowered.endswith("/match/"):
            return False
        return True

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        query_keys = {
            key.casefold()
            for key, _ in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
        }
        if query_keys & SEARCH_QUERY_KEYS:
            raise WikiAgentError(
                "invalid_request",
                "search queries are blocked by the nerdwallet adapter",
            )
        return super().validate_url(value)

    def accepts_content_type(self, content_type: str | None) -> bool:
        return (
            super().accepts_content_type(content_type)
            or bool(content_type and "xml" in content_type.lower())
        )

    def request_headers(self) -> dict[str, str]:
        return {"Accept-Language": "en-US,en;q=0.9"}

    def is_sitemap(self, fetch: FetchResult) -> bool:
        return (
            "/sitemaps/" in urllib.parse.urlsplit(fetch.url).path
            and (
                fetch.body.lstrip().startswith(b"<?xml")
                or bool(fetch.content_type and "xml" in fetch.content_type.lower())
            )
        )

    def is_feed(self, fetch: FetchResult) -> bool:
        return (
            urllib.parse.urlsplit(fetch.url).path.rstrip("/").endswith("/feed")
            and (
                b"<rss" in fetch.body[:1000].lower()
                or bool(
                    fetch.content_type
                    and (
                        "rss" in fetch.content_type.lower()
                        or "xml" in fetch.content_type.lower()
                    )
                )
            )
        )

    def parse_feed(self, fetch: FetchResult) -> list[dict[str, str]]:
        try:
            document = etree.fromstring(
                fetch.body,
                parser=etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    recover=False,
                    huge_tree=False,
                ),
            )
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise WikiAgentError("parse_error", "Unable to parse NerdWallet feed") from exc
        entries: list[dict[str, str]] = []
        for item in document.xpath("//*[local-name()='item']"):
            def first(name: str) -> str:
                values = item.xpath(f"./*[local-name()='{name}']/text()")
                return clean_text(values[0]) if values else ""

            href = self.normalize_link(first("link"), fetch.url)
            if not href:
                continue
            entries.append(
                {
                    "href": href,
                    "title": first("title"),
                    "published": first("pubDate"),
                    "author": first("creator"),
                    "description": first("description"),
                }
            )
        return entries

    def parse_sitemap(self, fetch: FetchResult) -> list[dict[str, str]]:
        try:
            document = etree.fromstring(
                fetch.body,
                parser=etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    recover=False,
                    huge_tree=False,
                ),
            )
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise WikiAgentError("parse_error", "Unable to parse NerdWallet sitemap") from exc
        entries: list[dict[str, str]] = []
        for location in document.xpath("//*[local-name()='loc']"):
            href = self.normalize_link(clean_text(location.text or ""), fetch.url)
            if not href:
                continue
            parent = location.getparent()
            modified = ""
            if parent is not None:
                values = parent.xpath("./*[local-name()='lastmod']/text()")
                if values:
                    modified = clean_text(values[0])
            entries.append({"href": href, "lastmod": modified})
        return entries

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path.casefold()
        if "/sitemaps/" in path and path.endswith(".xml"):
            return "listing"
        if path.rstrip("/").endswith("/feed"):
            return "listing"
        if path in {"", "/"}:
            return "index"
        if path.rstrip("/") in {"/finance", "/investing", "/retirement"}:
            return "index"
        if "/hubs/" in path:
            return "index"
        if "/best/" in path:
            return "listing"
        return "article"

    def sections(self, root: etree._Element) -> list[GenericSection]:
        headings = root.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6")
        if not headings:
            return super().sections(root)
        sections: list[GenericSection] = []
        first_boundary = self._heading_boundary(headings[0], root)
        lead_nodes = list(first_boundary.itersiblings(preceding=True))
        lead_nodes.reverse()
        sections.append(GenericSection("lead", "Lead", lead_nodes))
        for heading in headings:
            level = int(heading.tag[1])
            boundary = self._heading_boundary(heading, root)
            nodes: list[etree._Element] = []
            for sibling in boundary.itersiblings():
                next_headings = sibling.xpath(
                    ".//h1|.//h2|.//h3|.//h4|.//h5|.//h6"
                )
                if next_headings and int(next_headings[0].tag[1]) <= level:
                    break
                nodes.append(sibling)
            heading_text = element_text(heading)
            section_id = (
                boundary.xpath(".//*[@id][1]/@id")
                or boundary.xpath("./@id")
                or [re.sub(r"\W+", "_", heading_text).strip("_")]
            )[0]
            sections.append(
                GenericSection(section_id or "section", heading_text, nodes)
            )
        return sections

    def _heading_boundary(
        self,
        heading: etree._Element,
        root: etree._Element,
    ) -> etree._Element:
        boundary = heading
        while boundary.getparent() is not None and boundary.getparent() is not root:
            parent = boundary.getparent()
            children = [child for child in parent if isinstance(child.tag, str)]
            if len(children) != 1:
                break
            boundary = parent
        return boundary

    def visible_text(self, root: etree._Element) -> str:
        parts: list[str] = []
        for section in self.sections(root):
            if section.heading != "Lead":
                parts.append(section.heading)
            for node in section.nodes:
                text = clean_text(
                    " ".join(
                        node.xpath(
                            ".//text()[not(ancestor::script) and "
                            "not(ancestor::style) and not(ancestor::noscript) "
                            "and not(ancestor::nav) and not(ancestor::footer) "
                            "and not(ancestor::form)]"
                        )
                    )
                )
                if text:
                    parts.append(text)
        return "\n\n".join(parts)

    def metadata(
        self,
        document: html.HtmlElement,
        root: etree._Element,
    ) -> dict[str, Any]:
        fields: list[dict[str, str]] = []
        article_data = self._article_json_ld(document)
        if article_data:
            authors = article_data.get("author")
            author_names: list[str] = []
            for author in authors if isinstance(authors, list) else [authors]:
                if isinstance(author, dict) and isinstance(author.get("name"), str):
                    author_names.append(clean_text(author["name"]))
                elif isinstance(author, str):
                    author_names.append(clean_text(author))
            for key, label in (
                ("datePublished", "Published"),
                ("dateModified", "Updated"),
            ):
                if isinstance(article_data.get(key), str):
                    fields.append(
                        {"key": label, "value": clean_text(article_data[key])}
                    )
            if author_names:
                fields.insert(
                    0,
                    {"key": "Author", "value": ", ".join(author_names)},
                )
        image = article_data.get("image") if article_data else None
        if isinstance(image, dict):
            image = image.get("url")
        if isinstance(image, list):
            image = next((value for value in image if isinstance(value, str)), None)
        return {
            "image": image if isinstance(image, str) else None,
            "fields": fields,
        }

    def _article_json_ld(self, document: html.HtmlElement) -> dict[str, Any] | None:
        canonical_values = document.xpath(
            "//link[translate(@rel, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz')='canonical']/@href | "
            "//meta[@property='og:url']/@content"
        )
        canonical = canonical_values[0].rstrip("/") if canonical_values else None
        articles: list[dict[str, Any]] = []

        for script in document.xpath(
            "//script[translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz')='application/ld+json']"
        ):
            try:
                payload = json.loads(script.text or "")
            except json.JSONDecodeError:
                continue
            candidates: list[dict[str, Any]] = []
            if isinstance(payload, dict):
                candidates.append(payload)
                graph = payload.get("@graph")
                if isinstance(graph, list):
                    candidates.extend(
                        item for item in graph if isinstance(item, dict)
                    )
            elif isinstance(payload, list):
                candidates.extend(item for item in payload if isinstance(item, dict))
            for item in candidates:
                types = item.get("@type")
                if isinstance(types, str):
                    normalized_types = {types}
                elif isinstance(types, list):
                    normalized_types = {
                        value for value in types if isinstance(value, str)
                    }
                else:
                    normalized_types = set()
                if normalized_types & {"Article", "NewsArticle"}:
                    articles.append(item)
        if canonical:
            for article in articles:
                identities = [
                    article.get("@id"),
                    article.get("url"),
                    article.get("mainEntityOfPage"),
                ]
                for identity in identities:
                    if isinstance(identity, dict):
                        identity = identity.get("@id")
                    if isinstance(identity, str) and identity.rstrip("/") == canonical:
                        return article
        return articles[0] if articles else None

    def custom_lead(self, root: etree._Element) -> str | None:
        for paragraph in root.xpath(".//p"):
            text = element_text(paragraph)
            lowered = text.casefold()
            if len(text) < 80:
                continue
            if (
                "many or all of the products on this page" in lowered
                or (
                    "nerdwallet" in lowered
                    and ("writer" in lowered or "editor" in lowered)
                )
            ):
                continue
            return text
        return None

    def _sitemap_title(self, fetch: FetchResult) -> str:
        name = urllib.parse.unquote(
            urllib.parse.urlsplit(fetch.url).path.rstrip("/").rsplit("/", 1)[-1]
        )
        return re.sub(r"[-_]+", " ", name).strip().title() or "NerdWallet Sitemap"

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if self.is_feed(fetch):
            return self._traverse_feed(fetch, max_links, **options)
        if not self.is_sitemap(fetch):
            return super().traverse(fetch, max_links, **options)
        entries = self.parse_sitemap(fetch)
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
            "title": self._sitemap_title(fetch),
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

    def _traverse_feed(
        self,
        fetch: FetchResult,
        max_links: int,
        **options: Any,
    ) -> dict[str, Any]:
        entries = self.parse_feed(fetch)
        query = options.get("query")
        offset = options.get("offset", 0)
        page_types = set(options.get("page_types") or [])
        namespaces = set(options.get("namespaces") or [])
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        for entry in entries:
            context = " | ".join(
                value
                for value in (
                    entry["published"],
                    entry["author"],
                    entry["description"],
                )
                if value
            )
            if page_types and "article" not in page_types:
                continue
            if namespaces and self.name not in namespaces:
                continue
            if normalized_query and normalized_query not in (
                f"{entry['title']} {entry['href']} {context}".casefold()
            ):
                continue
            matches.append(
                {
                    "href": entry["href"],
                    "text": entry["title"] or entry["href"],
                    "context": context[: options.get("context_max_chars", 240)],
                    "page_type": "article",
                    "namespace": self.name,
                }
            )
        page = matches[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": "NerdWallet Feed",
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
        if self.is_feed(fetch):
            entries = self.parse_feed(fetch)
            include_entries = (
                selected_sections is None or "entries" in selected_sections
            )
            return {
                "url": fetch.url,
                "title": "NerdWallet Feed",
                "fetched_at": fetch.fetched_at,
                "infobox": {"image": None, "fields": []},
                "lead": f"NerdWallet WordPress feed containing {len(entries)} recent entries.",
                "sections": [
                    {
                        "id": "entries",
                        "heading": "Recent entries",
                        "summary": entries[0]["description"] if entries else None,
                        "link_sentences": [
                            {
                                "href": entry["href"],
                                "text": entry["title"] or entry["href"],
                                "sentence": entry["description"] or entry["published"],
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
        if not self.is_sitemap(fetch):
            return super().skim(
                fetch,
                selected_sections=selected_sections,
                max_links_per_section=max_links_per_section,
            )
        entries = self.parse_sitemap(fetch)
        preview = entries[:10]
        include_entries = selected_sections is None or "entries" in selected_sections
        return {
            "url": fetch.url,
            "title": self._sitemap_title(fetch),
            "fetched_at": fetch.fetched_at,
            "infobox": {"image": None, "fields": []},
            "lead": f"NerdWallet WordPress sitemap containing {len(entries)} entries.",
            "sections": [
                {
                    "id": "entries",
                    "heading": "Entries",
                    "summary": f"First {len(preview)} sitemap entries.",
                    "link_sentences": [
                        {
                            "href": entry["href"],
                            "text": entry["href"],
                            "sentence": (
                                f"Last modified: {entry['lastmod']}"
                                if entry["lastmod"]
                                else entry["href"]
                            ),
                        }
                        for entry in preview[:max_links_per_section]
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
        if self.is_feed(fetch):
            entries = self.parse_feed(fetch)
            text = "\n".join(
                "\t".join(
                    value
                    for value in (
                        entry["published"],
                        entry["title"],
                        entry["href"],
                        entry["description"],
                    )
                    if value
                )
                for entry in entries
            )
            skim = self.skim(
                fetch,
                selected_sections=None,
                max_links_per_section=10,
            )
            return {
                "url": fetch.url,
                "title": "NerdWallet Feed",
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
        if not self.is_sitemap(fetch):
            return super().read(fetch, output_format=output_format)
        entries = self.parse_sitemap(fetch)
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
            "title": self._sitemap_title(fetch),
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
