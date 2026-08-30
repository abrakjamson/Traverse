from __future__ import annotations

import json
import hmac
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, TextIO

from . import __version__
from .cache import Cache
from .config import Config
from .errors import WikiAgentError
from .fetcher import WikipediaFetcher
from . import parser


def now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


class StdioServer:
    def __init__(self, config: Config, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout):
        self.config = config
        self.stdin = stdin
        self.stdout = stdout
        self.cache = Cache(config.cache_path)
        self.fetcher = WikipediaFetcher(config, self.cache)
        self._write_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=config.max_concurrency)
        self._slots = threading.BoundedSemaphore(config.max_concurrency)
        self._authenticated = config.api_key is None
        self._client_key = "anonymous"
        self._shutdown_requested = False

    def run(self) -> int:
        try:
            self.fetcher.initialize()
            for line in self.stdin:
                if self._shutdown_requested:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    self._validate_envelope(request)
                    if request["method"] in {"hello", "health", "shutdown", "goodbye"}:
                        self._process(request)
                        if self._shutdown_requested:
                            break
                    elif not self._slots.acquire(blocking=False):
                        self._write_error(
                            request["id"],
                            WikiAgentError(
                                "rate_limited",
                                "Maximum request concurrency exceeded",
                                {"retry_after_seconds": 1},
                            ),
                        )
                    else:
                        future = self._executor.submit(self._process, request)
                        future.add_done_callback(self._release_slot)
                except json.JSONDecodeError:
                    self._write_error("", WikiAgentError("invalid_request", "Request is not valid JSON"))
                except WikiAgentError as exc:
                    request_id = request.get("id", "") if isinstance(request, dict) else ""
                    self._write_error(request_id, exc)
            return 0
        finally:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self.cache.close()

    def _release_slot(self, future: Future[None]) -> None:
        self._slots.release()
        try:
            future.result()
        except Exception:
            # _process translates operational failures. This only guards executor callback failures.
            pass

    @staticmethod
    def _validate_envelope(request: Any) -> None:
        if not isinstance(request, dict):
            raise WikiAgentError("invalid_request", "Request must be a JSON object")
        if not isinstance(request.get("id"), str) or not request["id"]:
            raise WikiAgentError("invalid_request", "id must be a non-empty string")
        if request.get("type") not in {"request", "hello", "goodbye"}:
            raise WikiAgentError("invalid_request", "type must be request, hello, or goodbye")
        if request.get("type") == "goodbye":
            request["method"] = "goodbye"
        if not isinstance(request.get("method"), str):
            raise WikiAgentError("invalid_request", "method must be a string")
        if "params" in request and not isinstance(request["params"], dict):
            raise WikiAgentError("invalid_request", "params must be an object")
        request.setdefault("params", {})

    def _process(self, request: dict[str, Any]) -> None:
        try:
            method = request["method"]
            if method == "hello":
                self._hello(request)
                return
            if method == "goodbye":
                self._write_response(request["id"], {"message": "goodbye"})
                self._shutdown_requested = True
                return
            self._require_auth()
            if method not in {"health", "shutdown"}:
                self.fetcher.client_rate_limiter.check(self._client_key)
            handlers = {
                "traverse": self._traverse,
                "skim": self._skim,
                "read": self._read,
                "health": self._health,
                "shutdown": self._shutdown,
            }
            handler = handlers.get(method)
            if handler is None:
                raise WikiAgentError("invalid_request", f"Unknown method: {method}")
            handler(request)
        except WikiAgentError as exc:
            self._write_error(request["id"], exc)
        except Exception:
            self._write_error(request["id"], WikiAgentError("internal_error", "Internal server error"))

    def _hello(self, request: dict[str, Any]) -> None:
        supplied = request["params"].get("api_key")
        if self.config.api_key is not None and (
            not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.config.api_key)
        ):
            raise WikiAgentError("unauthorized", "Invalid or missing API key")
        self._authenticated = True
        self._client_key = supplied or "anonymous"
        self._write_response(
            request["id"],
            {
                "server_version": __version__,
                "politeness": {
                    "crawl_delay_seconds": self.fetcher.crawl_delay_seconds,
                    "max_concurrency": self.config.max_concurrency,
                    "rate_limit_rps": self.config.rate_limit_rps,
                },
                "capabilities": ["traverse", "skim", "read", "health", "shutdown"],
            },
        )

    def _require_auth(self) -> None:
        if not self._authenticated:
            raise WikiAgentError("unauthorized", "Send an authorized hello request first")

    @staticmethod
    def _integer(params: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
        value = params.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise WikiAgentError("invalid_request", f"{name} must be an integer from {minimum} to {maximum}")
        return value

    def _traverse(self, request: dict[str, Any]) -> None:
        params = request["params"]
        max_links = self._integer(params, "max_links", 50, 1, 200)
        offset = self._integer(params, "offset", 0, 0, 1_000_000)
        context_max_chars = self._integer(params, "context_max_chars", 240, 0, 2000)
        cache_only = params.get("cache_only", False)
        if not isinstance(cache_only, bool):
            raise WikiAgentError("invalid_request", "cache_only must be a boolean")
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise WikiAgentError("invalid_request", "query must be a string")
        page_types = params.get("page_types")
        if page_types is not None and (
            not isinstance(page_types, list)
            or not all(value in {"article", "portal", "category", "other"} for value in page_types)
        ):
            raise WikiAgentError("invalid_request", "page_types contains an unsupported value")
        namespaces = params.get("namespaces")
        if namespaces is not None and (
            not isinstance(namespaces, list) or not all(isinstance(value, str) for value in namespaces)
        ):
            raise WikiAgentError("invalid_request", "namespaces must be an array of strings")
        fetched = self.fetcher.fetch(params.get("url"), cache_only=cache_only)
        self._write_response(
            request["id"],
            parser.traverse(
                fetched,
                max_links,
                query=query,
                page_types=page_types,
                namespaces=namespaces,
                offset=offset,
                context_max_chars=context_max_chars,
            ),
        )

    def _skim(self, request: dict[str, Any]) -> None:
        params = request["params"]
        sections = params.get("sections")
        if sections is not None and (
            not isinstance(sections, list) or not all(isinstance(value, str) for value in sections)
        ):
            raise WikiAgentError("invalid_request", "sections must be an array of strings")
        max_links = self._integer(params, "max_links_per_section", 10, 0, 100)
        ttl = params.get("cache_ttl_override")
        if ttl is not None:
            if not self.config.dev:
                raise WikiAgentError("invalid_request", "cache_ttl_override is only allowed in dev mode")
            if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 0:
                raise WikiAgentError("invalid_request", "cache_ttl_override must be a non-negative integer")
        fetched = self.fetcher.fetch(params.get("url"), ttl_seconds=ttl)
        self._write_response(
            request["id"],
            parser.skim(fetched, selected_sections=sections, max_links_per_section=max_links),
        )

    def _read(self, request: dict[str, Any]) -> None:
        params = request["params"]
        output_format = params.get("format", "plain")
        if output_format not in {"plain", "html"}:
            raise WikiAgentError("invalid_request", "format must be plain or html")
        stream = params.get("stream", False)
        if not isinstance(stream, bool):
            raise WikiAgentError("invalid_request", "stream must be a boolean")
        fetched = self.fetcher.fetch(params.get("url"))
        result = parser.read(fetched, output_format=output_format)
        if not stream:
            self._write_response(request["id"], result)
            return

        metadata = {key: value for key, value in result.items() if key not in {"text", "html", "skim"}}
        self._write_response(request["id"], metadata)
        chunk_source = result["html"] if output_format == "html" else result["text"]
        chunks = [chunk_source[index : index + 8192] for index in range(0, len(chunk_source), 8192)] or [""]
        for index, chunk in enumerate(chunks, start=1):
            self._write(
                {
                    "id": request["id"],
                    "type": "event",
                    "method": "read",
                    "timestamp": now(),
                    "event": {"chunk_index": index, "chunk": chunk, "final": index == len(chunks)},
                }
            )

    def _health(self, request: dict[str, Any]) -> None:
        self._write_response(
            request["id"],
            {
                "status": "ok",
                "robots_checked_at": self.fetcher.robots_checked_at,
                "crawl_delay_seconds": self.fetcher.crawl_delay_seconds,
            },
        )

    def _shutdown(self, request: dict[str, Any]) -> None:
        if self.config.api_key is None:
            raise WikiAgentError("unauthorized", "shutdown requires a configured API key")
        self._write_response(request["id"], {"accepted": True, "reason": request["params"].get("reason")})
        self._shutdown_requested = True

    def _write_response(self, request_id: str, result: dict[str, Any]) -> None:
        self._write({"id": request_id, "type": "response", "result": result, "timestamp": now()})

    def _write_error(self, request_id: str, error: WikiAgentError) -> None:
        self._write({"id": request_id, "type": "error", "error": error.payload(), "timestamp": now()})

    def _write(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            self.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.stdout.flush()
