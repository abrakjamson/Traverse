from __future__ import annotations

import urllib.parse

from .retail import RetailHtmlAdapter


class IkeaAdapter(RetailHtmlAdapter):
    name = "ikea"
    protected_domains = frozenset({"ikea.com"})
    hosts = frozenset({"ikea.com", "www.ikea.com"})
    canonical_host = "www.ikea.com"
    root_xpaths = (
        "//*[@id='main-content']",
        "//main",
        "//*[@role='main']",
        "//body",
    )
    blocked_segments = frozenset(
        {
            "browse-history",
            "buyback",
            "cart",
            "checkout",
            "compare",
            "favourites",
            "home-project-planner",
            "login",
            "order",
            "profile",
            "recommendations",
            "search",
            "shoppingcart",
            "watch",
        }
    )

    def path_allowed(self, path: str) -> bool:
        if path == "/":
            return True
        if not path.casefold().startswith("/us/en/"):
            return False
        segments = {
            segment.casefold()
            for segment in urllib.parse.unquote(path).split("/")
            if segment
        }
        return not bool(segments & self.blocked_segments)

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path.casefold()
        if "/p/" in path:
            return "article"
        if "/cat/" in path:
            return "listing"
        if path in {"/", "/us/en/", "/us/en"}:
            return "index"
        return "other"
