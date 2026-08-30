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

from .cache import Cache, CacheEntry
from .config import Config
from .errors import WikiAgentError
from .urls import ALLOWED_NAMESPACES, BLOCKED_NAMESPACES, namespace_for_title
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


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


class WikipediaFetcher:
    def __init__(self, config: Config, cache: Cache):
        self.config = config
        self.cache = cache
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_checked_at: float | None = None
        self._crawl_delay = config.crawl_delay_seconds
        self._host_lock = threading.Lock()
        self._last_host_request = 0.0
        self.client_rate_limiter = SlidingRateLimiter(config.rate_limit_rps)

    @property
    def robots_checked_at(self) -> str | None:
        return iso_timestamp(self._robots_checked_at) if self._robots_checked_at else None

    @property
    def crawl_delay_seconds(self) -> float:
        return self._crawl_delay

    def initialize(self) -> None:
        self.refresh_robots()

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")

        parsed = urllib.parse.urlsplit(value)
        expected = urllib.parse.urlsplit(self.config.base_url)
        if parsed.scheme != expected.scheme or parsed.hostname != expected.hostname:
            raise WikiAgentError(
                "invalid_request",
                f"url must use the configured Wikipedia origin {self.config.base_url}",
            )
        if parsed.username or parsed.password or parsed.port or parsed.query:
            raise WikiAgentError("invalid_request", "url must not contain credentials, a port, or a query")
        if not parsed.path.startswith("/wiki/"):
            raise WikiAgentError("invalid_request", "only /wiki/* pages are supported")

        raw_path_lower = parsed.path.lower()
        if "%2f" in raw_path_lower or "%5c" in raw_path_lower:
            raise WikiAgentError("invalid_request", "encoded path separators are not allowed")
        decoded_path = urllib.parse.unquote(parsed.path)
        if any(segment == ".." for segment in decoded_path.split("/")):
            raise WikiAgentError("invalid_request", "parent path segments are not allowed")

        title = decoded_path.removeprefix("/wiki/")
        if not title:
            raise WikiAgentError("invalid_request", "url must identify a Wikipedia page")
        namespace = namespace_for_title(title)
        if namespace in BLOCKED_NAMESPACES:
            raise WikiAgentError("invalid_request", f"the {namespace.replace('_', ' ')} namespace is not supported")
        if namespace not in ALLOWED_NAMESPACES:
            raise WikiAgentError("invalid_request", f"the {namespace.replace('_', ' ')} namespace is not supported")

        clean_path = urllib.parse.quote(decoded_path, safe="/:()_")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", ""))

    def refresh_robots(self, force: bool = False) -> None:
        now = time.time()
        if (
            not force
            and self._robots_checked_at is not None
            and now - self._robots_checked_at <= self.config.robots_ttl_seconds
        ):
            return
        saved = self.cache.get_state("robots")
        if (
            not force
            and saved
            and now - float(saved["checked_at"]) <= self.config.robots_ttl_seconds
        ):
            self._set_robots(saved["body"], float(saved["checked_at"]))
            return

        robots_url = f"{self.config.base_url}/robots.txt"
        try:
            request = urllib.request.Request(
                robots_url,
                headers={"User-Agent": self.config.user_agent, "Accept": "text/plain"},
            )
            self._wait_for_host()
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                body = response.read(1_000_001)
                if len(body) > 1_000_000:
                    raise WikiAgentError("upstream_error", "robots.txt exceeded the size limit")
                text = body.decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as exc:
            if saved:
                self._set_robots(saved["body"], float(saved["checked_at"]))
                return
            # Fail conservatively: permit only the already restricted /wiki/ surface.
            text = "User-agent: *\nAllow: /wiki/\nDisallow: /\n"
            self._set_robots(text, 0)
            return

        self.cache.put_state("robots", {"body": text, "checked_at": now})
        self._set_robots(text, now)

    def _set_robots(self, text: str, checked_at: float) -> None:
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots.set_url(f"{self.config.base_url}/robots.txt")
        self._robots.parse(text.splitlines())
        delay = self._robots.crawl_delay(self.config.user_agent)
        if delay is None:
            delay = self._robots.crawl_delay("*")
        self._crawl_delay = max(self.config.crawl_delay_seconds, float(delay or 0))
        self._robots_checked_at = checked_at

    def _wait_for_host(self) -> None:
        with self._host_lock:
            elapsed = time.monotonic() - self._last_host_request
            if elapsed < self._crawl_delay:
                time.sleep(self._crawl_delay - elapsed)
            self._last_host_request = time.monotonic()

    def fetch(self, url: str, *, cache_only: bool = False, ttl_seconds: int | None = None) -> FetchResult:
        normalized = self.validate_url(url)
        self.refresh_robots()
        if not self._robots.can_fetch(self.config.user_agent, normalized):
            raise WikiAgentError("disallowed_by_robots", "robots.txt disallows this path")

        ttl = self.config.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        cached = self.cache.get(normalized)
        if cached and cached.is_fresh(ttl):
            return self._from_cache(cached, cached_flag=True)
        if cache_only:
            if cached:
                return self._from_cache(cached, cached_flag=True)
            raise WikiAgentError("not_cached", "No cached response exists for this URL")

        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        }
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        for attempt in range(self.config.max_retries + 1):
            request = urllib.request.Request(normalized, headers=headers)
            try:
                self._wait_for_host()
                with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise WikiAgentError("upstream_error", "Wikipedia response exceeded 10 MiB")
                    content_type = response.headers.get("Content-Type")
                    if content_type and "html" not in content_type.lower():
                        raise WikiAgentError("parse_error", "Wikipedia returned a non-HTML response")
                    entry = self.cache.put(
                        normalized,
                        body,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_type=content_type,
                    )
                    return self._from_cache(entry, cached_flag=False)
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached:
                    return self._from_cache(self.cache.touch(cached), cached_flag=True)
                if exc.code in {429, 503} and attempt < self.config.max_retries:
                    time.sleep(min(self._retry_delay(exc.headers.get("Retry-After"), attempt), 60))
                    continue
                if exc.code >= 500:
                    raise WikiAgentError("upstream_error", f"Wikipedia returned HTTP {exc.code}") from exc
                raise WikiAgentError("upstream_error", f"Wikipedia returned HTTP {exc.code}") from exc
            except WikiAgentError:
                raise
            except (OSError, urllib.error.URLError) as exc:
                if attempt < self.config.max_retries:
                    time.sleep(self._retry_delay(None, attempt))
                    continue
                raise WikiAgentError("upstream_error", "Failed to fetch Wikipedia") from exc

        raise WikiAgentError("upstream_error", "Failed to fetch Wikipedia")

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
    def _from_cache(entry: CacheEntry, *, cached_flag: bool) -> FetchResult:
        return FetchResult(
            url=entry.url,
            body=entry.body,
            fetched_at=iso_timestamp(entry.fetched_at),
            cached=cached_flag,
            etag=entry.etag,
            last_modified=entry.last_modified,
            content_type=entry.content_type,
        )
