from __future__ import annotations

import io
import json
from argparse import Namespace

from wiki_agent.config import load_config
from wiki_agent.server import StdioServer


def test_hello_health_and_goodbye(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKI_AGENT_API_KEY", "secret")
    config = load_config(
        Namespace(dev=True, cache_path=tmp_path / "cache.sqlite3", base_url="https://en.wikipedia.org")
    )
    requests = "\n".join(
        [
            json.dumps({"id": "1", "type": "request", "method": "hello", "params": {"api_key": "secret"}}),
            json.dumps({"id": "2", "type": "request", "method": "health", "params": {}}),
            json.dumps({"id": "3", "type": "goodbye", "params": {}}),
        ]
    )
    stdin = io.StringIO(requests)
    stdout = io.StringIO()
    server = StdioServer(config, stdin, stdout)
    monkeypatch.setattr(server.fetcher, "initialize", lambda: server.fetcher._set_robots(
        "User-agent: *\nAllow: /wiki/\n", 1
    ))

    assert server.run() == 0

    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert messages[0]["result"]["capabilities"] == ["traverse", "skim", "read", "health", "shutdown"]
    assert messages[1]["result"]["status"] == "ok"
    assert messages[2]["result"]["message"] == "goodbye"


def test_rejects_unauthorized_hello(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKI_AGENT_API_KEY", "secret")
    config = load_config(
        Namespace(dev=True, cache_path=tmp_path / "cache.sqlite3", base_url="https://en.wikipedia.org")
    )
    stdin = io.StringIO(
        json.dumps({"id": "1", "type": "request", "method": "hello", "params": {"api_key": "wrong"}})
    )
    stdout = io.StringIO()
    server = StdioServer(config, stdin, stdout)
    monkeypatch.setattr(server.fetcher, "initialize", lambda: server.fetcher._set_robots(
        "User-agent: *\nAllow: /wiki/\n", 1
    ))

    server.run()

    message = json.loads(stdout.getvalue())
    assert message["type"] == "error"
    assert message["error"]["code"] == "unauthorized"
