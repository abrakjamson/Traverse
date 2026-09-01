from __future__ import annotations

import urllib.parse

from .generic import GenericHtmlAdapter


class ImdbAdapter(GenericHtmlAdapter):
    name = "imdb"
    protected_domains = frozenset({"imdb.com"})
    hosts = frozenset({"help.imdb.com"})
    root_xpaths = (
        "//*[@id='article_content']",
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' article_content ')]",
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' content_container ')]",
    )
    allowed_path_prefixes = ("/", "/imdb", "/article/")
    blocked_path_prefixes = ("/search", "/contact", "/article/issues", "/login")

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path
        if "imdb-site-index" in path or path.rstrip("/") in {"", "/imdb"}:
            return "index"
        return "article"
