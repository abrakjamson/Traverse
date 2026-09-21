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


def env_value(primary: str, legacy: str, oldest: str, default: str | None = None) -> str | None:
    return os.getenv(primary, os.getenv(legacy, os.getenv(oldest, default)))


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
            env_value(
                "TRAVERSE_CACHE_PATH",
                "PUREPATH_CACHE_PATH",
                "WIKI_AGENT_CACHE_PATH",
                str(default_cache_path()),
            )
        ),
    )
    parser.add_argument(
        "--base-url",
        default=env_value(
            "TRAVERSE_BASE_URL",
            "PUREPATH_BASE_URL",
            "WIKI_AGENT_BASE_URL",
            "https://en.wikipedia.org",
        ),
        help="Development mirror origin; non-Wikipedia origins require --dev.",
    )
    return parser


def load_config(args: argparse.Namespace) -> Config:
    base_url = args.base_url.rstrip("/")
    if base_url != "https://en.wikipedia.org" and not args.dev:
        raise SystemExit("A non-Wikipedia --base-url is only allowed with --dev.")

    return Config(
        api_key=env_value("TRAVERSE_API_KEY", "PUREPATH_API_KEY", "WIKI_AGENT_API_KEY"),
        user_agent=env_value(
            "TRAVERSE_USER_AGENT",
            "PUREPATH_USER_AGENT",
            "WIKI_AGENT_USER_AGENT",
            "Traverse/0.4 (+https://github.com/abrakjamson/Traverse)",
        ),
        crawl_delay_seconds=float(
            env_value(
                "TRAVERSE_CRAWL_DELAY",
                "PUREPATH_CRAWL_DELAY",
                "WIKI_AGENT_CRAWL_DELAY",
                "1",
            )
        ),
        cache_ttl_seconds=int(
            env_value(
                "TRAVERSE_CACHE_TTL",
                "PUREPATH_CACHE_TTL",
                "WIKI_AGENT_CACHE_TTL",
                "86400",
            )
        ),
        cache_path=args.cache_path,
        max_concurrency=int(
            env_value(
                "TRAVERSE_MAX_CONCURRENCY",
                "PUREPATH_MAX_CONCURRENCY",
                "WIKI_AGENT_MAX_CONCURRENCY",
                "1",
            )
        ),
        rate_limit_rps=float(
            env_value(
                "TRAVERSE_RATE_LIMIT_RPS",
                "PUREPATH_RATE_LIMIT_RPS",
                "WIKI_AGENT_RATE_LIMIT_RPS",
                "1",
            )
        ),
        robots_ttl_seconds=int(
            env_value(
                "TRAVERSE_ROBOTS_TTL",
                "PUREPATH_ROBOTS_TTL",
                "WIKI_AGENT_ROBOTS_TTL",
                "86400",
            )
        ),
        request_timeout_seconds=float(
            env_value(
                "TRAVERSE_REQUEST_TIMEOUT",
                "PUREPATH_REQUEST_TIMEOUT",
                "WIKI_AGENT_REQUEST_TIMEOUT",
                "20",
            )
        ),
        max_retries=int(
            env_value(
                "TRAVERSE_MAX_RETRIES",
                "PUREPATH_MAX_RETRIES",
                "WIKI_AGENT_MAX_RETRIES",
                "3",
            )
        ),
        dev=args.dev,
        base_url=base_url,
    )
