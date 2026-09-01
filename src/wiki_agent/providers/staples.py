from __future__ import annotations

import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from ..errors import WikiAgentError
from .retail import RetailHtmlAdapter

if TYPE_CHECKING:
    from ..fetcher import FetchResult


MAX_EMBEDDED_PRODUCTS = 500


class StaplesAdapter(RetailHtmlAdapter):
    name = "staples"
    protected_domains = frozenset({"staples.com"})
    hosts = frozenset({"staples.com", "www.staples.com"})
    canonical_host = "www.staples.com"
    root_xpaths = (
        "//*[@id='main-content']",
        "//main",
        "//*[@role='main']",
        "//body",
    )
    category_pattern = re.compile(
        r"/[^/]+/cat_(?:SC|CL)\d+/?$",
        re.IGNORECASE,
    )
    product_pattern = re.compile(
        r"/[^/]+/product_\d+/?$",
        re.IGNORECASE,
    )

    def path_allowed(self, path: str) -> bool:
        return (
            path == "/"
            or bool(self.category_pattern.fullmatch(path))
            or bool(self.product_pattern.fullmatch(path))
        )

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path
        if self.product_pattern.fullmatch(path):
            return "article"
        if "/CAT_SC" in path.upper():
            return "index"
        if self.category_pattern.fullmatch(path):
            return "listing"
        return "index"

    def embedded_products(self, fetch: FetchResult) -> list[dict[str, str]]:
        document, _ = self.parse(fetch)
        scripts = document.xpath("//script[@id='__NEXT_DATA__']/text()")
        if not scripts:
            return []
        try:
            payload = json.loads(scripts[0])
        except json.JSONDecodeError as exc:
            raise WikiAgentError(
                "parse_error",
                "Unable to parse Staples product listing data",
            ) from exc
        products: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in self._json_objects(payload):
            value = item.get("url")
            title = item.get("title")
            item_id = item.get("itemId")
            if (
                not isinstance(value, str)
                or not isinstance(title, str)
                or not isinstance(item_id, str)
                or f"product_{item_id}" not in value
            ):
                continue
            href = self.normalize_link(value, fetch.url)
            if not href or href in seen:
                continue
            seen.add(href)
            details = [
                item.get("price"),
                item.get("pricePerUnit"),
                (
                    f"{item['rating']} stars from {item['ratingCount']} ratings"
                    if isinstance(item.get("rating"), (int, float))
                    and isinstance(item.get("ratingCount"), int)
                    else None
                ),
            ]
            context = " | ".join(
                str(detail).strip()
                for detail in details
                if isinstance(detail, (str, int, float)) and str(detail).strip()
            )
            products.append(
                {
                    "href": href,
                    "text": title.strip(),
                    "context": context,
                    "page_type": "article",
                    "namespace": self.name,
                }
            )
            if len(products) >= MAX_EMBEDDED_PRODUCTS:
                break
        return products

    def traverse(
        self,
        fetch: FetchResult,
        max_links: int,
        **options: Any,
    ) -> dict[str, Any]:
        if self.page_type(fetch.url) != "listing":
            return super().traverse(fetch, max_links, **options)
        result = super().traverse(
            fetch,
            5_000,
            query=None,
            page_types=None,
            namespaces=None,
            offset=0,
            context_max_chars=options.get("context_max_chars", 240),
        )
        combined = result["links"] + self.embedded_products(fetch)
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
        links = matches[offset : offset + max_links]
        result["links"] = links
        result["meta"].update(
            {
                "link_count": len(links),
                "offset": offset,
                "next_offset": (
                    offset + len(links)
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
        return result
