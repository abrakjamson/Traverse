from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    api_key: str | None
    user_agent: str
    crawl_delay_seconds: float
    cache_ttl_seconds: int
    cache_path: Path
    max_concurrency: int
    rate_limit_rps: float
    robots_ttl_seconds: int
    request_timeout_seconds: float
    max_retries: int
    dev: bool
    base_url: str


def default_cache_path() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Traverse" / "cache.sqlite3"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Traverse" / "cache.sqlite3"
    root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "traverse" / "cache.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Traverse MCP server.")
    parser.add_argument("--dev", action="store_true", help="Allow development-only cache overrides.")
    parser.add_argument(
        "--ndjson",
        action="store_true",
        help="Use the legacy native NDJSON protocol instead of standard MCP stdio.",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=Path(
            os.getenv("TRAVERSE_CACHE_PATH", str(default_cache_path()))
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("TRAVERSE_BASE_URL", "https://en.wikipedia.org"),
        help="Development mirror origin; non-Wikipedia origins require --dev.",
    )
    return parser


def load_config(args: argparse.Namespace) -> Config:
    base_url = args.base_url.rstrip("/")
    if base_url != "https://en.wikipedia.org" and not args.dev:
        raise SystemExit("A non-Wikipedia --base-url is only allowed with --dev.")

    return Config(
        api_key=os.getenv("TRAVERSE_API_KEY"),
        user_agent=os.getenv(
            "TRAVERSE_USER_AGENT",
            "Traverse",
        ),
        crawl_delay_seconds=float(
            os.getenv("TRAVERSE_CRAWL_DELAY", "1")
        ),
        cache_ttl_seconds=int(
            os.getenv("TRAVERSE_CACHE_TTL", "86400")
        ),
        cache_path=args.cache_path,
        max_concurrency=int(
            os.getenv("TRAVERSE_MAX_CONCURRENCY", "1")
        ),
        rate_limit_rps=float(
            os.getenv("TRAVERSE_RATE_LIMIT_RPS", "1")
        ),
        robots_ttl_seconds=int(
            os.getenv("TRAVERSE_ROBOTS_TTL", "86400")
        ),
        request_timeout_seconds=float(
            os.getenv("TRAVERSE_REQUEST_TIMEOUT", "20")
        ),
        max_retries=int(
            os.getenv("TRAVERSE_MAX_RETRIES", "3")
        ),
        dev=args.dev,
        base_url=base_url,
    )
