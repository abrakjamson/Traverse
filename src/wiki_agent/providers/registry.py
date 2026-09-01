from __future__ import annotations

import urllib.parse

from ..config import Config
from ..errors import WikiAgentError
from .arxiv import ArxivAdapter
from .base import SiteAdapter
from .imdb import ImdbAdapter
from .ikea import IkeaAdapter
from .nerdwallet import NerdWalletAdapter
from .npr import NprAdapter
from .fred import FredAdapter
from .foxsports import FoxSportsAdapter
from .staples import StaplesAdapter
from .stockanalysis import StockAnalysisAdapter
from .web import WebAdapter
from .webmd import WebMdAdapter
from .wikipedia import WikipediaAdapter


def normalized_hostname(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").rstrip(".").casefold()
    except ValueError:
        return ""


class ProviderRegistry:
    def __init__(self, adapters: list[SiteAdapter]):
        self.adapters = adapters
        self._by_name = {adapter.name: adapter for adapter in adapters}

    def resolve(self, url: str) -> SiteAdapter:
        fallback: SiteAdapter | None = None
        for adapter in self.adapters:
            if adapter.is_fallback:
                fallback = adapter
                continue
            if adapter.matches(url):
                return adapter
        hostname = normalized_hostname(url)
        for adapter in self.adapters:
            if any(
                hostname == domain or hostname.endswith(f".{domain}")
                for domain in adapter.protected_domains
            ):
                return adapter
        if fallback and fallback.matches(url):
            return fallback
        raise WikiAgentError("invalid_request", "url does not match a supported site")

    def by_name(self, name: str) -> SiteAdapter:
        return self._by_name[name]

    @property
    def names(self) -> list[str]:
        return list(self._by_name)


def build_registry(config: Config) -> ProviderRegistry:
    return ProviderRegistry(
        [
            WikipediaAdapter(config.base_url),
            ImdbAdapter(),
            ArxivAdapter(),
            NerdWalletAdapter(),
            NprAdapter(),
            FredAdapter(),
            StockAnalysisAdapter(),
            WebMdAdapter(),
            FoxSportsAdapter(),
            IkeaAdapter(),
            StaplesAdapter(),
            WebAdapter(),
        ]
    )
