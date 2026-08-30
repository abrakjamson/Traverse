from __future__ import annotations

import email.utils
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .cache import Cache, CacheEntry
from .config import Config
from .errors import WikiAgentError

if TYPE_CHECKING:
    from .providers import ProviderRegistry
    from .providers.base import SiteAdapter


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def iso_timestamp(timestamp: float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time(), tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    body: bytes
    fetched_at: str
    cached: bool
    etag: str | None
    last_modified: str | None
    content_type: str | None
    provider: str = "wikipedia"


@dataclass(slots=True)
class HostState:
    robots: urllib.robotparser.RobotFileParser
    robots_checked_at: float | None
    crawl_delay: float
    last_request: float
    lock: threading.Lock


class SlidingRateLimiter:
    def __init__(self, requests_per_second: float):
        self._interval = 1.0 / max(requests_per_second, 0.001)
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(key)
            if last is not None and now - last < self._interval:
                retry_after = max(1, int(self._interval - (now - last) + 0.999))
                raise WikiAgentError(
                    "rate_limited",
                    "Too many requests",
                    {"retry_after_seconds": retry_after},
                )
            self._last_seen[key] = now


class PoliteFetcher:
    def __init__(
        self,
        config: Config,
        cache: Cache,
        registry: ProviderRegistry | None = None,
    ):
        from .providers import build_registry

        self.config = config
        self.cache = cache
        self.registry = registry or build_registry(config)
        self._states: dict[str, HostState] = {}
        self._states_lock = threading.Lock()
        self.client_rate_limiter = SlidingRateLimiter(config.rate_limit_rps)

    @property
    def robots_checked_at(self) -> str | None:
        timestamps = [
            state.robots_checked_at
            for state in self._states.values()
            if state.robots_checked_at is not None
        ]
        return iso_timestamp(max(timestamps)) if timestamps else None

    @property
    def crawl_delay_seconds(self) -> float:
        delays = [state.crawl_delay for state in self._states.values()]
        return max(delays, default=self.config.crawl_delay_seconds)

    def provider_status(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for origin, state in sorted(self._states.items()):
            results.append(
                {
                    "origin": origin,
                    "robots_checked_at": (
                        iso_timestamp(state.robots_checked_at)
                        if state.robots_checked_at
                        else None
                    ),
                    "crawl_delay_seconds": state.crawl_delay,
                }
            )
        return results

    def initialize(self) -> None:
        # Robots are loaded lazily per site so arXiv's 15-second delay cannot block MCP startup.
        return

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str):
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        return self.registry.resolve(value).validate_url(value)

    def _origin(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        return f"{parsed.scheme}://{parsed.hostname}"

    def _state(self, origin: str) -> HostState:
        with self._states_lock:
            state = self._states.get(origin)
            if state is None:
                state = HostState(
                    robots=urllib.robotparser.RobotFileParser(),
                    robots_checked_at=None,
                    crawl_delay=self.config.crawl_delay_seconds,
                    last_request=0.0,
                    lock=threading.Lock(),
                )
                self._states[origin] = state
            return state

    def refresh_robots(self, adapter: SiteAdapter, url: str, force: bool = False) -> HostState:
        origin = self._origin(url)
        state = self._state(origin)
        now = time.time()
        if (
            not force
            and state.robots_checked_at is not None
            and now - state.robots_checked_at <= self.config.robots_ttl_seconds
        ):
            return state

        state_key = f"robots:{origin}"
        saved = self.cache.get_state(state_key)
        if (
            not force
            and saved
            and now - float(saved["checked_at"]) <= self.config.robots_ttl_seconds
        ):
            self._set_robots(
                saved["body"],
                float(saved["checked_at"]),
                origin=origin,
                robots_url=adapter.robots_url(url),
            )
            return state

        robots_url = adapter.robots_url(url)
        try:
            request = urllib.request.Request(
                robots_url,
                headers={"User-Agent": self.config.user_agent, "Accept": "text/plain"},
            )
            body, _ = self._request(state, request, max_bytes=1_000_000)
            text = body.decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError, WikiAgentError):
            if saved:
                self._set_robots(
                    saved["body"],
                    float(saved["checked_at"]),
                    origin=origin,
                    robots_url=robots_url,
                )
                return state
            # Fail closed until the site's robots policy can be retrieved.
            self._set_robots(
                "User-agent: *\nDisallow: /\n",
                0,
                origin=origin,
                robots_url=robots_url,
            )
            return state

        self.cache.put_state(state_key, {"body": text, "checked_at": now})
        self._set_robots(text, now, origin=origin, robots_url=robots_url)
        return state

    def _set_robots(
        self,
        text: str,
        checked_at: float,
        *,
        origin: str | None = None,
        robots_url: str | None = None,
    ) -> None:
        origin = origin or self.config.base_url
        state = self._state(origin)
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url or f"{origin}/robots.txt")
        parser.parse(text.splitlines())
        delay = parser.crawl_delay(self.config.user_agent)
        if delay is None:
            delay = parser.crawl_delay("*")
        state.robots = parser
        state.crawl_delay = max(self.config.crawl_delay_seconds, float(delay or 0))
        state.robots_checked_at = checked_at

    def _request(
        self,
        state: HostState,
        request: urllib.request.Request,
        *,
        max_bytes: int,
    ) -> tuple[bytes, urllib.response.addinfourl]:
        with state.lock:
            elapsed = time.monotonic() - state.last_request
            if elapsed < state.crawl_delay:
                time.sleep(state.crawl_delay - elapsed)
            state.last_request = time.monotonic()
            response = urllib.request.build_opener(NoRedirectHandler()).open(
                request,
                timeout=self.config.request_timeout_seconds,
            )
            with response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise WikiAgentError("upstream_error", "Response exceeded the size limit")
                return body, response

    def _request_with_redirects(
        self,
        url: str,
        adapter: SiteAdapter,
        headers: dict[str, str],
    ) -> tuple[bytes, urllib.response.addinfourl, SiteAdapter, str]:
        current_url = url
        current_adapter = adapter
        current_headers = headers
        for redirect_count in range(MAX_REDIRECTS + 1):
            state = self.refresh_robots(current_adapter, current_url)
            if not state.robots.can_fetch(self.config.user_agent, current_url):
                raise WikiAgentError(
                    "disallowed_by_robots",
                    "robots.txt disallows this path",
                )
            request = urllib.request.Request(current_url, headers=current_headers)
            try:
                body, response = self._request(
                    state,
                    request,
                    max_bytes=MAX_RESPONSE_BYTES,
                )
                return body, response, current_adapter, current_url
            except urllib.error.HTTPError as exc:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise
                if redirect_count >= MAX_REDIRECTS:
                    raise WikiAgentError(
                        "upstream_error",
                        "Site returned too many redirects",
                    ) from exc
                location = exc.headers.get("Location")
                if not location:
                    raise WikiAgentError(
                        "upstream_error",
                        "Site returned a redirect without a destination",
                    ) from exc
                destination = urllib.parse.urljoin(current_url, location)
                current_adapter = self.registry.resolve(destination)
                current_url = current_adapter.validate_url(destination)
                current_headers = {
                    key: value
                    for key, value in headers.items()
                    if key not in {"If-None-Match", "If-Modified-Since"}
                }
        raise WikiAgentError("upstream_error", "Site returned too many redirects")

    def fetch(
        self,
        url: object,
        *,
        cache_only: bool = False,
        ttl_seconds: int | None = None,
    ) -> FetchResult:
        normalized = self.validate_url(url)
        adapter = self.registry.resolve(normalized)
        state = self.refresh_robots(adapter, normalized)
        if not state.robots.can_fetch(self.config.user_agent, normalized):
            raise WikiAgentError("disallowed_by_robots", "robots.txt disallows this path")

        ttl = self.config.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        cache_url = normalized
        cache_adapter = adapter
        redirect_state = self.cache.get_state(f"redirect:{normalized}")
        if redirect_state:
            try:
                cache_url = self.validate_url(redirect_state["target"])
                cache_adapter = self.registry.resolve(cache_url)
            except (KeyError, TypeError, WikiAgentError):
                cache_url = normalized
                cache_adapter = adapter
        if cache_url != normalized:
            cache_state = self.refresh_robots(cache_adapter, cache_url)
            if not cache_state.robots.can_fetch(self.config.user_agent, cache_url):
                raise WikiAgentError(
                    "disallowed_by_robots",
                    "robots.txt disallows the cached redirect destination",
                )
        cached = self.cache.get(cache_url)
        if cached and cached.is_fresh(ttl):
            return self._from_cache(
                cached,
                cached_flag=True,
                provider=cache_adapter.name,
            )
        if cache_only:
            if cached:
                return self._from_cache(
                    cached,
                    cached_flag=True,
                    provider=cache_adapter.name,
                )
            raise WikiAgentError("not_cached", "No cached response exists for this URL")

        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        }
        if cached and cache_url == normalized and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cache_url == normalized and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        for attempt in range(self.config.max_retries + 1):
            try:
                body, response, final_adapter, final_url = self._request_with_redirects(
                    normalized,
                    adapter,
                    headers,
                )
                content_type = response.headers.get("Content-Type")
                if content_type and "html" not in content_type.lower():
                    raise WikiAgentError("parse_error", "Site returned a non-HTML response")
                entry = self.cache.put(
                    final_url,
                    body,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    content_type=content_type,
                )
                self.cache.put_state(
                    f"redirect:{normalized}",
                    {"target": final_url},
                )
                return self._from_cache(
                    entry,
                    cached_flag=False,
                    provider=final_adapter.name,
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached:
                    return self._from_cache(
                        self.cache.touch(cached),
                        cached_flag=True,
                        provider=adapter.name,
                    )
                if exc.code in {429, 503} and attempt < self.config.max_retries:
                    time.sleep(min(self._retry_delay(exc.headers.get("Retry-After"), attempt), 60))
                    continue
                raise WikiAgentError("upstream_error", f"Site returned HTTP {exc.code}") from exc
            except WikiAgentError:
                raise
            except (OSError, urllib.error.URLError) as exc:
                if attempt < self.config.max_retries:
                    time.sleep(self._retry_delay(None, attempt))
                    continue
                raise WikiAgentError("upstream_error", "Failed to fetch site") from exc

        raise WikiAgentError("upstream_error", "Failed to fetch site")

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                if parsed:
                    return max(0.0, parsed.timestamp() - time.time())
        return (2**attempt) + random.uniform(0, 0.5)

    @staticmethod
    def _from_cache(
        entry: CacheEntry,
        *,
        cached_flag: bool,
        provider: str,
    ) -> FetchResult:
        return FetchResult(
            url=entry.url,
            body=entry.body,
            fetched_at=iso_timestamp(entry.fetched_at),
            cached=cached_flag,
            etag=entry.etag,
            last_modified=entry.last_modified,
            content_type=entry.content_type,
            provider=provider,
        )


WikipediaFetcher = PoliteFetcher
