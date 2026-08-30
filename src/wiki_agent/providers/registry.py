from __future__ import annotations

from ..config import Config
from ..errors import WikiAgentError
from .arxiv import ArxivAdapter
from .base import SiteAdapter
from .imdb import ImdbAdapter
from .wikipedia import WikipediaAdapter


class ProviderRegistry:
    def __init__(self, adapters: list[SiteAdapter]):
        self.adapters = adapters
        self._by_name = {adapter.name: adapter for adapter in adapters}

    def resolve(self, url: str) -> SiteAdapter:
        for adapter in self.adapters:
            if adapter.matches(url):
                return adapter
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
        ]
    )
