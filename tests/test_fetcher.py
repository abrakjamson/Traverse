from __future__ import annotations

import time
from argparse import Namespace

import pytest

from wiki_agent.cache import Cache
from wiki_agent.config import load_config
from wiki_agent.errors import WikiAgentError
from wiki_agent.fetcher import SlidingRateLimiter, WikipediaFetcher


def config(tmp_path):
    return load_config(
        Namespace(dev=True, cache_path=tmp_path / "cache.sqlite3", base_url="https://en.wikipedia.org")
    )


def test_url_validation_restricts_origin_and_namespaces(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)

    assert fetcher.validate_url("https://en.wikipedia.org/wiki/Portal:Science") == (
        "https://en.wikipedia.org/wiki/Portal:Science"
    )
    with pytest.raises(WikiAgentError, match="configured Wikipedia origin"):
        fetcher.validate_url("https://example.com/wiki/Test")
    with pytest.raises(WikiAgentError, match="special namespace"):
        fetcher.validate_url("https://en.wikipedia.org/wiki/Special:Random")
    assert fetcher.validate_url("https://en.wikipedia.org/wiki/100%25_(album)") == (
        "https://en.wikipedia.org/wiki/100%25_(album)"
    )
    with pytest.raises(WikiAgentError, match="encoded path separators"):
        fetcher.validate_url("https://en.wikipedia.org/wiki/..%2Fw%2Fload.php")
    assert fetcher.validate_url("https://en.wikipedia.org/wiki/Dune:_Part_Two") == (
        "https://en.wikipedia.org/wiki/Dune:_Part_Two"
    )
    cache.close()


def test_cache_only_returns_stale_cached_page(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)
    fetcher._set_robots("User-agent: *\nAllow: /wiki/\n", time.time())
    url = "https://en.wikipedia.org/wiki/Test"
    cache.put(url, b"<html></html>", etag=None, last_modified=None, content_type="text/html", fetched_at=1)

    result = fetcher.fetch(url, cache_only=True)

    assert result.cached is True
    assert result.body == b"<html></html>"
    cache.close()


def test_rate_limiter_reports_retry_after() -> None:
    limiter = SlidingRateLimiter(1)
    limiter.check("key")

    with pytest.raises(WikiAgentError) as caught:
        limiter.check("key")

    assert caught.value.code == "rate_limited"
    assert caught.value.details == {"retry_after_seconds": 1}
