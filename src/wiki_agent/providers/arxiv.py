from __future__ import annotations

import urllib.parse
from typing import Any

from lxml import etree, html

from .generic import GenericHtmlAdapter, element_text


class ArxivAdapter(GenericHtmlAdapter):
    name = "arxiv"
    hosts = frozenset({"arxiv.org"})
    root_xpaths = ("//main", "//*[@id='content']", "//body")
    allowed_path_prefixes = (
        "/",
        "/archive/",
        "/year/",
        "/list/",
        "/abs/",
        "/html/",
        "/catchup/",
    )
    blocked_path_prefixes = (
        "/search",
        "/find",
        "/api",
        "/pdf",
        "/e-print",
        "/src",
        "/user",
        "/form",
        "/auth",
        "/login",
    )
    allowed_query_keys = frozenset({"skip", "show"})

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path
        if path.startswith("/abs/"):
            return "abstract"
        if path.startswith("/html/"):
            return "article"
        if path.startswith("/list/"):
            return "listing"
        if path.startswith(("/archive/", "/year/", "/catchup/")) or path == "/":
            return "index"
        return "other"

    def title(self, document: html.HtmlElement, root: etree._Element) -> str:
        titles = root.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' title ')]"
        )
        if titles:
            return element_text(titles[0]).removeprefix("Title:").strip()
        return super().title(document, root)

    def custom_lead(self, root: etree._Element) -> str | None:
        abstracts = root.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' abstract ')]"
        )
        return element_text(abstracts[0]).removeprefix("Abstract:").strip() if abstracts else None

    def metadata(self, document: html.HtmlElement, root: etree._Element) -> dict[str, Any]:
        fields: list[dict[str, str]] = []
        selectors = (
            ("Authors", ".//*[contains(concat(' ', normalize-space(@class), ' '), ' authors ')]"),
            ("Subjects", ".//*[contains(concat(' ', normalize-space(@class), ' '), ' subjects ')]"),
            (
                "Submission history",
                ".//*[contains(concat(' ', normalize-space(@class), ' '), ' submission-history ')]",
            ),
        )
        for key, xpath in selectors:
            nodes = root.xpath(xpath)
            if nodes and (value := element_text(nodes[0])):
                fields.append({"key": key, "value": value})
        return {"image": None, "fields": fields}
