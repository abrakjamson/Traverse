from __future__ import annotations

import email.utils
import http.client
import random
import socket
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


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, addresses: tuple[str, ...], **kwargs):
        super().__init__(host, **kwargs)
        self._addresses = addresses

    def connect(self) -> None:
        last_error: OSError | None = None
        for address in self._addresses:
            try:
                sock = socket.create_connection(
                    (address, self.port),
                    self.timeout,
                    self.source_address,
                )
                self.sock = self._context.wrap_socket(
                    sock,
                    server_hostname=self.host,
                )
                return
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError("No validated addresses are available")


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, addresses: tuple[str, ...]):
        super().__init__()
        self._addresses = addresses

    def https_open(self, request):
        return self.do_open(
            lambda host, **kwargs: PinnedHTTPSConnection(
                host,
                addresses=self._addresses,
                **kwargs,
            ),
            request,
        )


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
        _, normalized = self._resolve_adapter(value)
        return normalized

    def _resolve_adapter(self, value: str) -> tuple[SiteAdapter, str]:
        current = value
        previous_adapter: SiteAdapter | None = None
        for _ in range(len(self.registry.adapters) + 1):
            adapter = self.registry.resolve(current)
            normalized = adapter.validate_url(current)
            if adapter is previous_adapter and normalized == current:
                return adapter, normalized
            resolved = self.registry.resolve(normalized)
            if resolved is adapter:
                return adapter, normalized
            previous_adapter = adapter
            current = normalized
        raise WikiAgentError("invalid_request", "url provider resolution did not stabilize")

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

    def refresh_robots(
        self,
        adapter: SiteAdapter,
        url: str,
        force: bool = False,
        network_addresses: tuple[str, ...] | None = None,
    ) -> HostState:
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
            body, _ = self._request(
                state,
                request,
                max_bytes=1_000_000,
                network_addresses=network_addresses,
            )
            text = body.decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError, WikiAgentError):
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
        network_addresses: tuple[str, ...] | None = None,
    ) -> tuple[bytes, urllib.response.addinfourl]:
        with state.lock:
            elapsed = time.monotonic() - state.last_request
            if elapsed < state.crawl_delay:
                time.sleep(state.crawl_delay - elapsed)
            state.last_request = time.monotonic()
            handlers: list[urllib.request.BaseHandler] = [NoRedirectHandler()]
            if network_addresses is not None:
                handlers = [
                    urllib.request.ProxyHandler({}),
                    NoRedirectHandler(),
                    PinnedHTTPSHandler(network_addresses),
                ]
            response = urllib.request.build_opener(*handlers).open(
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
        initial_network_addresses: tuple[str, ...] | None,
    ) -> tuple[bytes, urllib.response.addinfourl, SiteAdapter, str]:
        current_url = url
        current_adapter = adapter
        current_headers = headers
        network_addresses = initial_network_addresses
        for redirect_count in range(MAX_REDIRECTS + 1):
            state = self.refresh_robots(
                current_adapter,
                current_url,
                network_addresses=network_addresses,
            )
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
                    network_addresses=network_addresses,
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
                current_adapter, current_url = self._resolve_adapter(destination)
                network_addresses = current_adapter.validate_network_destination(
                    current_url
                )
                current_headers = {
                    "User-Agent": self.config.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "identity",
                }
                current_headers.update(current_adapter.request_headers())
        raise WikiAgentError("upstream_error", "Site returned too many redirects")

    def fetch(
        self,
        url: object,
        *,
        cache_only: bool = False,
        ttl_seconds: int | None = None,
    ) -> FetchResult:
        if not isinstance(url, str):
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        adapter, normalized = self._resolve_adapter(url)
        network_addresses = adapter.validate_network_destination(normalized)
        state = self.refresh_robots(
            adapter,
            normalized,
            network_addresses=network_addresses,
        )
        if not state.robots.can_fetch(self.config.user_agent, normalized):
            raise WikiAgentError("disallowed_by_robots", "robots.txt disallows this path")

        ttl = self.config.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        cache_url = normalized
        cache_adapter = adapter
        redirect_state = self.cache.get_state(f"redirect:{normalized}")
        if redirect_state:
            try:
                cache_adapter, cache_url = self._resolve_adapter(
                    redirect_state["target"]
                )
            except (KeyError, TypeError, WikiAgentError):
                cache_url = normalized
                cache_adapter = adapter
        if cache_url != normalized:
            cache_network_addresses = cache_adapter.validate_network_destination(
                cache_url
            )
            cache_state = self.refresh_robots(
                cache_adapter,
                cache_url,
                network_addresses=cache_network_addresses,
            )
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
            **adapter.request_headers(),
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
                    network_addresses,
                )
                content_type = response.headers.get("Content-Type")
                if not final_adapter.accepts_content_type(content_type):
                    raise WikiAgentError("parse_error", "Site returned an unsupported content type")
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
