from __future__ import annotations

import argparse
import os
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PurePath MCP server.")
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
            os.getenv(
                "PUREPATH_CACHE_PATH",
                os.getenv("WIKI_AGENT_CACHE_PATH", ".purepath-cache.sqlite3"),
            )
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("PUREPATH_BASE_URL", os.getenv("WIKI_AGENT_BASE_URL", "https://en.wikipedia.org")),
        help="Development mirror origin; non-Wikipedia origins require --dev.",
    )
    return parser


def load_config(args: argparse.Namespace) -> Config:
    base_url = args.base_url.rstrip("/")
    if base_url != "https://en.wikipedia.org" and not args.dev:
        raise SystemExit("A non-Wikipedia --base-url is only allowed with --dev.")

    return Config(
        api_key=os.getenv("PUREPATH_API_KEY", os.getenv("WIKI_AGENT_API_KEY")),
        user_agent=os.getenv(
            "PUREPATH_USER_AGENT",
            os.getenv(
                "WIKI_AGENT_USER_AGENT",
                "PurePath/0.2 (+https://github.com/abrakjamson/PurePath)",
            ),
        ),
        crawl_delay_seconds=float(
            os.getenv("PUREPATH_CRAWL_DELAY", os.getenv("WIKI_AGENT_CRAWL_DELAY", "1"))
        ),
        cache_ttl_seconds=int(os.getenv("PUREPATH_CACHE_TTL", os.getenv("WIKI_AGENT_CACHE_TTL", "86400"))),
        cache_path=args.cache_path,
        max_concurrency=int(
            os.getenv("PUREPATH_MAX_CONCURRENCY", os.getenv("WIKI_AGENT_MAX_CONCURRENCY", "1"))
        ),
        rate_limit_rps=float(
            os.getenv("PUREPATH_RATE_LIMIT_RPS", os.getenv("WIKI_AGENT_RATE_LIMIT_RPS", "1"))
        ),
        robots_ttl_seconds=int(
            os.getenv("PUREPATH_ROBOTS_TTL", os.getenv("WIKI_AGENT_ROBOTS_TTL", "86400"))
        ),
        request_timeout_seconds=float(
            os.getenv("PUREPATH_REQUEST_TIMEOUT", os.getenv("WIKI_AGENT_REQUEST_TIMEOUT", "20"))
        ),
        max_retries=int(os.getenv("PUREPATH_MAX_RETRIES", os.getenv("WIKI_AGENT_MAX_RETRIES", "3"))),
        dev=args.dev,
        base_url=base_url,
    )
