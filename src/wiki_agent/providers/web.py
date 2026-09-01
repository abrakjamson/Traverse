from __future__ import annotations

import ipaddress
import io
import re
import socket
import urllib.parse
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..errors import WikiAgentError
from ..urls import normalize_external_https_url
from .generic import GenericHtmlAdapter


MAX_PDF_PAGES = 500
MAX_PDF_TEXT_CHARS = 5_000_000


class WebAdapter(GenericHtmlAdapter):
    name = "web"
    is_fallback = True
    root_xpaths = ("//main", "//*[@role='main']", "//*[@id='content']", "//article", "//body")

    def matches(self, url: str) -> bool:
        if not isinstance(url, str):
            return False
        try:
            return urllib.parse.urlsplit(url).scheme == "https"
        except ValueError:
            return False

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        normalized = normalize_external_https_url(value, value)
        if not normalized:
            raise WikiAgentError(
                "invalid_request",
                "generic web URLs must use public HTTPS without credentials or a port",
            )
        return normalized

    def validate_network_destination(self, url: str) -> tuple[str, ...]:
        hostname = urllib.parse.urlsplit(url).hostname
        if not hostname:
            raise WikiAgentError("invalid_request", "url must include a hostname")
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise WikiAgentError("upstream_error", "Unable to resolve web host") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise WikiAgentError(
                "invalid_request",
                "generic web URLs must resolve only to public network addresses",
            )
        return tuple(sorted(str(address) for address in addresses))

    def accepts_content_type(self, content_type: str | None) -> bool:
        return (
            content_type is None
            or "html" in content_type.lower()
            or "application/pdf" in content_type.lower()
        )

    def page_type(self, url: str) -> str:
        return "index" if urllib.parse.urlsplit(url).path in {"", "/"} else "article"

    def _is_pdf(self, fetch) -> bool:
        return (
            bool(fetch.content_type and "application/pdf" in fetch.content_type.lower())
            or fetch.body.startswith(b"%PDF-")
        )

    def _pdf(self, fetch) -> tuple[str, str, list[str]]:
        try:
            reader = PdfReader(io.BytesIO(fetch.body))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise WikiAgentError(
                    "parse_error",
                    f"PDF exceeds the {MAX_PDF_PAGES}-page extraction limit",
                )
            pages: list[str] = []
            extracted_characters = 0
            for page in reader.pages:
                page_text = (page.extract_text() or "").strip()
                extracted_characters += len(page_text)
                if extracted_characters > MAX_PDF_TEXT_CHARS:
                    raise WikiAgentError(
                        "parse_error",
                        "PDF extracted text exceeds the size limit",
                    )
                pages.append(page_text)
        except (OSError, PyPdfError, TypeError, ValueError) as exc:
            raise WikiAgentError("parse_error", "Unable to parse PDF document") from exc
        text = "\n\n".join(page for page in pages if page)
        if not text:
            raise WikiAgentError("parse_error", "PDF contains no extractable text")
        metadata_title = reader.metadata.title if reader.metadata else None
        fallback = urllib.parse.unquote(
            urllib.parse.urlsplit(fetch.url).path.rstrip("/").rsplit("/", 1)[-1]
        )
        return (metadata_title or fallback or "PDF document").strip(), text, pages

    def traverse(self, fetch, max_links: int, **options: Any) -> dict[str, Any]:
        if not self._is_pdf(fetch):
            return super().traverse(fetch, max_links, **options)
        title, text, _ = self._pdf(fetch)
        query = options.get("query")
        offset = options.get("offset", 0)
        context_max_chars = options.get("context_max_chars", 240)
        page_types = set(options.get("page_types") or [])
        namespaces = set(options.get("namespaces") or [])
        normalized_query = query.casefold().strip() if query else None
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in re.finditer(r"https://[^\s<>{}\[\]\"]+", text):
            href = normalize_external_https_url(
                match.group(0).rstrip(".,;:)"),
                fetch.url,
            )
            if not href or href in seen:
                continue
            if page_types and "external" not in page_types:
                continue
            if namespaces and "external" not in namespaces:
                continue
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            context = text[start : end if end >= 0 else len(text)].strip()
            if normalized_query and normalized_query not in f"{href} {context}".casefold():
                continue
            seen.add(href)
            links.append(
                {
                    "href": href,
                    "text": href,
                    "context": context[:context_max_chars],
                    "page_type": "external",
                    "namespace": "external",
                }
            )
        page = links[offset : offset + max_links]
        return {
            "url": fetch.url,
            "title": title,
            "fetched_at": fetch.fetched_at,
            "links": page,
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "pdf",
                    "link_count": len(page),
                    "offset": offset,
                    "next_offset": (
                        offset + len(page)
                        if offset + max_links < len(links)
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
        fetch,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        if not self._is_pdf(fetch):
            return super().skim(
                fetch,
                selected_sections=selected_sections,
                max_links_per_section=max_links_per_section,
            )
        title, text, pages = self._pdf(fetch)
        wanted = set(selected_sections or [])
        sections = []
        for index, page in enumerate(pages, start=1):
            section_id = f"page_{index}"
            if selected_sections is not None and section_id not in wanted:
                continue
            if not page:
                continue
            sections.append(
                {
                    "id": section_id,
                    "heading": f"Page {index}",
                    "summary": page[:500],
                    "link_sentences": [],
                }
            )
            if selected_sections is None and len(sections) >= 10:
                break
        return {
            "url": fetch.url,
            "title": title,
            "fetched_at": fetch.fetched_at,
            "infobox": {"image": None, "fields": []},
            "lead": text[:1200],
            "sections": sections,
            "see_also": [],
            "categories": [],
            "tables": [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "pdf",
                    "word_count": len(text.split()),
                    "total_sections": len(pages),
                    "sections_truncated": (
                        selected_sections is None and len(pages) > len(sections)
                    ),
                    "tables_truncated": False,
                    "reliability_hint": "medium",
                },
            ),
        }

    def read(self, fetch, *, output_format: str) -> dict[str, Any]:
        if not self._is_pdf(fetch):
            return super().read(fetch, output_format=output_format)
        title, text, _ = self._pdf(fetch)
        skim = self.skim(
            fetch,
            selected_sections=None,
            max_links_per_section=10,
        )
        return {
            "url": fetch.url,
            "title": title,
            "fetched_at": fetch.fetched_at,
            "text": text,
            "html": None,
            "skim": skim,
            "tables": [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "pdf",
                    "word_count": len(text.split()),
                    "sections_returned": len(skim["sections"]),
                },
            ),
        }
