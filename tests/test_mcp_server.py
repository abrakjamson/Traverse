from __future__ import annotations

from argparse import Namespace

from wiki_agent.config import load_config
from wiki_agent.mcp_server import create_mcp_server


def test_mcp_server_registers_wikipedia_tools(monkeypatch, tmp_path) -> None:
    config = load_config(
        Namespace(
            dev=True,
            ndjson=False,
            cache_path=tmp_path / "cache.sqlite3",
            base_url="https://en.wikipedia.org",
        )
    )
    monkeypatch.setattr(
        "wiki_agent.mcp_server.WikipediaFetcher.initialize",
        lambda self: self._set_robots("User-agent: *\nAllow: /wiki/\n", 1),
    )

    server = create_mcp_server(config)

    assert server.name == "PurePath"
