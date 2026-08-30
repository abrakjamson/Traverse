from __future__ import annotations

import time
import urllib.error
from email.message import Message
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


def test_url_validation_routes_known_and_generic_sites(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)

    assert fetcher.validate_url("https://en.wikipedia.org/wiki/Portal:Science") == (
        "https://en.wikipedia.org/wiki/Portal:Science"
    )
    assert fetcher.validate_url("https://example.com/wiki/Test") == (
        "https://example.com/wiki/Test"
    )
    with pytest.raises(WikiAgentError, match="public HTTPS"):
        fetcher.validate_url("https://localhost/wiki/Test")
    with pytest.raises(WikiAgentError, match="blocked"):
        fetcher.validate_url("https://arxiv.org./search/?query=agents")
    with pytest.raises(WikiAgentError, match="blocked"):
        fetcher.validate_url("https://help.imdb.com./search/?q=account")
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


def test_fetch_rejects_non_string_url(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)

    with pytest.raises(WikiAgentError) as caught:
        fetcher.fetch({"url": "https://en.wikipedia.org/wiki/Test"})

    assert caught.value.code == "invalid_request"
    cache.close()


def test_redirect_destination_is_validated_before_request(tmp_path, monkeypatch) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)
    fetcher._set_robots(
        "User-agent: *\nAllow: /\n",
        time.time(),
        origin="https://arxiv.org",
        robots_url="https://arxiv.org/robots.txt",
    )
    headers = Message()
    headers["Location"] = "/pdf/2401.00001"
    calls = 0

    def redirect(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            "https://arxiv.org/abs/2401.00001",
            302,
            "Found",
            headers,
            None,
        )

    monkeypatch.setattr(fetcher, "_request", redirect)

    with pytest.raises(WikiAgentError, match="blocked"):
        fetcher.fetch("https://arxiv.org/abs/2401.00001")

    assert calls == 1
    cache.close()


def test_cache_only_resolves_validated_redirect_alias(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    fetcher = WikipediaFetcher(config(tmp_path), cache)
    source = "https://arxiv.org/abs/2401.00001"
    destination = "https://arxiv.org/html/2401.00001"
    cache.put(
        destination,
        b"<html><main>Paper</main></html>",
        etag=None,
        last_modified=None,
        content_type="text/html",
    )
    cache.put_state(f"redirect:{source}", {"target": destination})
    fetcher._set_robots(
        "User-agent: *\nAllow: /\n",
        time.time(),
        origin="https://arxiv.org",
        robots_url="https://arxiv.org/robots.txt",
    )

    result = fetcher.fetch(source, cache_only=True)

    assert result.url == destination
    assert result.provider == "arxiv"
    assert result.cached is True
    cache.close()
