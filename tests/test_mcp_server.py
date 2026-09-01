from __future__ import annotations

import asyncio
from argparse import Namespace

import pytest

from wiki_agent.config import load_config
from wiki_agent.mcp_server import create_mcp_server


@pytest.fixture
def server(monkeypatch, tmp_path):
    config = load_config(
        Namespace(
            dev=True,
            ndjson=False,
            cache_path=tmp_path / "cache.sqlite3",
            base_url="https://en.wikipedia.org",
        )
    )
    monkeypatch.setattr(
        "wiki_agent.mcp_server.PoliteFetcher.initialize",
        lambda self: self._set_robots("User-agent: *\nAllow: /wiki/\n", 1),
    )

    return create_mcp_server(config)


def test_mcp_server_registers_purepath_tools(server) -> None:
    tools = {tool.name for tool in asyncio.run(server.list_tools())}

    assert server.name == "PurePath"
    assert tools == {"help", "traverse", "skim", "read", "health"}


def test_help_describes_tools_sites_and_traversal_examples(server) -> None:
    _, result = asyncio.run(server.call_tool("help", {}))

    assert result["server"] == "PurePath"
    assert set(result["tools"]) == {"help", "traverse", "skim", "read", "health"}
    assert {site["provider"] for site in result["supported_sites"]} == {
        "wikipedia",
        "imdb",
        "arxiv",
        "nerdwallet",
        "npr",
        "fred",
        "stockanalysis",
        "webmd",
        "foxsports",
        "ikea",
        "staples",
        "web",
    }
    assert len(result["traversal_examples"]) >= 5
    assert all(example["calls"] for example in result["traversal_examples"])
    assert any(
        call["tool"] == "traverse"
        for example in result["traversal_examples"]
        for call in example["calls"]
    )
