from __future__ import annotations

import re
import urllib.parse
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from ..errors import WikiAgentError
from ..urls import normalize_external_https_url
from .base import SiteAdapter

if TYPE_CHECKING:
    from ..fetcher import FetchResult


SPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def element_text(node: etree._Element) -> str:
    clone = deepcopy(node)
    for child in clone.xpath(
        ".//script|.//style|.//noscript|.//svg|.//math|.//form|.//nav|.//footer"
    ):
        child.drop_tree()
    return clean_text(clone.text_content())


def sanitized_html(root: etree._Element) -> str:
    clone = deepcopy(root)
    for node in clone.xpath(
        ".//script|.//style|.//noscript|.//iframe|.//object|.//embed|.//form|"
        ".//svg|.//math|.//meta|.//link|.//base|.//template"
    ):
        node.drop_tree()
    allowed_tags = {
        "a",
        "article",
        "b",
        "blockquote",
        "body",
        "br",
        "caption",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "time",
        "tr",
        "u",
        "ul",
    }
    global_attributes = {"class", "dir", "id", "lang", "title"}
    tag_attributes = {
        "a": {"href"},
        "img": {"alt", "height", "src", "width"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan", "scope"},
        "time": {"datetime"},
    }
    for node in list(clone.iter()):
        if not isinstance(node.tag, str):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        if node.tag.lower() not in allowed_tags:
            node.drop_tag()
            continue
        for attribute in list(node.attrib):
            attribute_lower = attribute.lower()
            if (
                attribute_lower not in global_attributes
                and attribute_lower not in tag_attributes.get(node.tag.lower(), set())
            ):
                del node.attrib[attribute]
                continue
            if attribute_lower in {"href", "src"}:
                value = node.attrib[attribute].strip()
                if not value.startswith("https://"):
                    del node.attrib[attribute]
    return etree.tostring(clone, encoding="unicode", method="html")


@dataclass(frozen=True, slots=True)
class GenericSection:
    id: str
    heading: str
    nodes: list[etree._Element]


class GenericHtmlAdapter(SiteAdapter):
    hosts: frozenset[str]
    root_xpaths: tuple[str, ...] = ("//main", "//*[@id='content']", "//body")
    blocked_path_prefixes: tuple[str, ...] = ()
    allowed_path_prefixes: tuple[str, ...] = ("/",)
    allowed_query_keys: frozenset[str] = frozenset()

    def matches(self, url: str) -> bool:
        hostname = (urllib.parse.urlsplit(url).hostname or "").rstrip(".").casefold()
        return hostname in self.hosts

    def path_allowed(self, path: str) -> bool:
        def matches(prefix: str) -> bool:
            return path == "/" if prefix == "/" else path == prefix.rstrip("/") or path.startswith(prefix)

        return (
            any(matches(prefix) for prefix in self.allowed_path_prefixes)
            and not any(matches(prefix) for prefix in self.blocked_path_prefixes)
        )

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if parsed.scheme != "https" or hostname not in self.hosts:
            raise WikiAgentError("invalid_request", f"url is not supported by the {self.name} adapter")
        if parsed.username or parsed.password or parsed.port:
            raise WikiAgentError("invalid_request", "url must not contain credentials or a port")
        decoded_path = urllib.parse.unquote(parsed.path or "/")
        if any(segment == ".." for segment in decoded_path.split("/")):
            raise WikiAgentError("invalid_request", "parent path segments are not allowed")
        if not self.path_allowed(decoded_path):
            raise WikiAgentError("invalid_request", f"path is blocked by the {self.name} adapter")
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if any(key not in self.allowed_query_keys for key, _ in query_pairs):
            query_pairs = []
        path = urllib.parse.quote(decoded_path, safe="/:@()_,-.")
        query = urllib.parse.urlencode(query_pairs)
        return urllib.parse.urlunsplit(("https", hostname, path, query, ""))

    def robots_url(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname or ""
        authority = f"[{hostname}]" if ":" in hostname else hostname
        return f"https://{authority}/robots.txt"

    def normalize_link(self, value: str | None, base_url: str) -> str | None:
        if not value or value.startswith(("javascript:", "mailto:", "tel:")):
            return None
        absolute = urllib.parse.urljoin(base_url, value)
        try:
            return self.validate_url(absolute)
        except WikiAgentError:
            return None

    def discovery_link(self, value: str | None, base_url: str) -> str | None:
        internal = self.normalize_link(value, base_url)
        if internal:
            return internal
        external = normalize_external_https_url(value, base_url)
        if not external:
            return None
        if urllib.parse.urlsplit(external).hostname == urllib.parse.urlsplit(base_url).hostname:
            return None
        return external

    def parse(self, fetch: FetchResult) -> tuple[html.HtmlElement, etree._Element]:
        try:
            encoding = None
            if fetch.content_type:
                match = re.search(
                    r"charset\s*=\s*[\"']?([^;\"'\s]+)",
                    fetch.content_type,
                    re.IGNORECASE,
                )
                if match:
                    encoding = match.group(1)
            document = html.fromstring(
                fetch.body,
                parser=html.HTMLParser(encoding=encoding),
            )
            document.make_links_absolute(fetch.url)
        except (etree.ParserError, ValueError) as exc:
            raise WikiAgentError("parse_error", f"Unable to parse {self.name} HTML") from exc
        for xpath in self.root_xpaths:
            roots = document.xpath(xpath)
            if roots:
                return document, roots[0]
        raise WikiAgentError("parse_error", f"{self.name} page content was not found")

    def title(self, document: html.HtmlElement, root: etree._Element) -> str:
        headings = root.xpath("(.//h1)[1]")
        if headings:
            return element_text(headings[0])
        titles = document.xpath("//title/text()")
        if titles:
            return clean_text(titles[0])
        raise WikiAgentError("parse_error", f"{self.name} page title was not found")

    def page_type(self, url: str) -> str:
        return "article"

    def metadata(self, document: html.HtmlElement, root: etree._Element) -> dict[str, Any]:
        return {"image": None, "fields": []}

    def sections(self, root: etree._Element) -> list[GenericSection]:
        headings = root.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6")
        if not headings:
            return [GenericSection("lead", "Lead", [root])]
        sections: list[GenericSection] = []
        first_heading = headings[0]
        lead_nodes = list(first_heading.itersiblings(preceding=True))
        lead_nodes.reverse()
        sections.append(GenericSection("lead", "Lead", lead_nodes))
        for heading in headings:
            level = int(heading.tag[1])
            nodes: list[etree._Element] = []
            sibling = heading.getnext()
            while sibling is not None:
                if isinstance(sibling.tag, str) and re.fullmatch(r"h[1-6]", sibling.tag):
                    if int(sibling.tag[1]) <= level:
                        break
                nodes.append(sibling)
                sibling = sibling.getnext()
            heading_text = element_text(heading)
            section_id = heading.get("id") or re.sub(r"\W+", "_", heading_text).strip("_")
            sections.append(GenericSection(section_id or "section", heading_text, nodes))
        return sections

    def lead(self, root: etree._Element, sections: list[GenericSection]) -> str:
        custom = self.custom_lead(root)
        if custom:
            return custom
        lead = "\n\n".join(
            text
            for node in sections[0].nodes
            if isinstance(node.tag, str) and node.tag in {"p", "div"}
            if (text := element_text(node))
        )
        if lead:
            return lead
        for paragraph in root.xpath(".//p"):
            if any(
                ancestor.tag in {"nav", "footer", "form"}
                for ancestor in paragraph.iterancestors()
            ):
                continue
            if text := element_text(paragraph):
                return text
        return ""

    def custom_lead(self, root: etree._Element) -> str | None:
        return None

    def visible_text(self, root: etree._Element) -> str:
        parts: list[str] = []
        for node in root.xpath(
            ".//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//p|.//li|"
            ".//dt|.//dd|.//blockquote"
        ):
            if any(ancestor.tag in {"script", "style", "noscript", "nav", "footer", "form"} for ancestor in node.iterancestors()):
                continue
            text = element_text(node)
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    def extract_links(self, nodes: list[etree._Element], base_url: str, limit: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for node in nodes:
            for anchor in node.xpath(".//a[@href]"):
                href = self.discovery_link(anchor.get("href"), base_url)
                text = clean_text(anchor.text_content())
                if not href or not text or href in seen:
                    continue
                seen.add(href)
                context = anchor
                for _ in range(5):
                    if context.tag in {"p", "li", "dd", "td", "div"}:
                        break
                    if context.getparent() is None:
                        break
                    context = context.getparent()
                sentence_source = element_text(context)
                sentences = SENTENCE_RE.split(sentence_source)
                sentence = next((item for item in sentences if text in item), sentence_source)
                results.append({"href": href, "text": text, "sentence": sentence})
                if len(results) >= limit:
                    return results
        return results

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        document, root = self.parse(fetch)
        query = options.get("query")
        offset = options.get("offset", 0)
        context_max_chars = options.get("context_max_chars", 240)
        page_types = set(options.get("page_types") or [])
        namespaces = {
            value.casefold().replace(" ", "_")
            for value in options.get("namespaces") or []
        }
        normalized_query = query.casefold().strip() if query else None
        matches: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in root.xpath(".//a[@href]"):
            href = self.discovery_link(anchor.get("href"), fetch.url)
            text = clean_text(anchor.text_content())
            if not href or not text or href in seen:
                continue
            seen.add(href)
            context_node = anchor
            for _ in range(5):
                if context_node.tag in {"p", "li", "dd", "td", "div"}:
                    break
                if context_node.getparent() is None:
                    break
                context_node = context_node.getparent()
            context = element_text(context_node)
            external = (
                urllib.parse.urlsplit(href).hostname
                != urllib.parse.urlsplit(fetch.url).hostname
            )
            target_type = "external" if external else self.page_type(href)
            namespace = "external" if external else self.name
            if page_types and target_type not in page_types:
                continue
            if namespaces and namespace not in namespaces:
                continue
            if normalized_query and normalized_query not in f"{text} {href} {context}".casefold():
                continue
            matches.append(
                {
                    "href": href,
                    "text": text,
                    "context": context[:context_max_chars],
                    "page_type": target_type,
                    "namespace": namespace,
                }
            )
            if len(matches) >= offset + max_links + 1:
                break
        has_more = len(matches) > offset + max_links
        links = matches[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": self.title(document, root),
            "fetched_at": fetch.fetched_at,
            "links": links,
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": self.page_type(fetch.url),
                    "link_count": len(links),
                    "offset": offset,
                    "next_offset": offset + len(links) if has_more else None,
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
        document, root = self.parse(fetch)
        all_sections = self.sections(root)
        wanted = set(selected_sections or [])
        included = (
            [section for section in all_sections if section.id in wanted]
            if selected_sections is not None
            else all_sections[:10]
        )
        sections = []
        for section in included:
            text = "\n\n".join(
                value
                for node in section.nodes
                if isinstance(node.tag, str)
                and node.tag in {"p", "li", "dl", "dt", "dd", "div", "blockquote"}
                if (value := element_text(node))
            )
            sections.append(
                {
                    "id": section.id,
                    "heading": section.heading,
                    "summary": SENTENCE_RE.split(text, maxsplit=1)[0] if text else None,
                    "link_sentences": self.extract_links(
                        section.nodes, fetch.url, max_links_per_section
                    ),
                }
            )
        text = self.visible_text(root)
        return {
            "url": fetch.url,
            "title": self.title(document, root),
            "fetched_at": fetch.fetched_at,
            "infobox": self.metadata(document, root),
            "lead": self.lead(root, all_sections),
            "sections": sections,
            "see_also": [],
            "categories": [],
            "tables": [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": self.page_type(fetch.url),
                    "word_count": len(text.split()),
                    "total_sections": len(all_sections),
                    "sections_truncated": selected_sections is None and len(all_sections) > len(included),
                    "tables_truncated": False,
                    "reliability_hint": "medium",
                },
            ),
        }

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        document, root = self.parse(fetch)
        skim_result = self.skim(fetch, selected_sections=None, max_links_per_section=10)
        text = self.visible_text(root)
        return {
            "url": fetch.url,
            "title": self.title(document, root),
            "fetched_at": fetch.fetched_at,
            "text": text,
            "html": sanitized_html(root) if output_format == "html" else None,
            "skim": skim_result,
            "tables": [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": self.page_type(fetch.url),
                    "word_count": len(text.split()),
                    "sections_returned": len(skim_result["sections"]),
                },
            ),
        }

    def result_meta(self, fetch: FetchResult, values: dict[str, Any]) -> dict[str, Any]:
        return {
            **values,
            "provider": self.name,
            "cached": fetch.cached,
            "etag": fetch.etag,
            "last_modified": fetch.last_modified,
            "cache_control": "max-age=86400",
        }
