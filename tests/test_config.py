from __future__ import annotations

from wiki_agent.config import build_parser, load_config


def test_traverse_environment_configures_runtime(monkeypatch, tmp_path) -> None:
    traverse_cache = tmp_path / "traverse.sqlite3"
    monkeypatch.setenv("TRAVERSE_CACHE_PATH", str(traverse_cache))
    monkeypatch.setenv("TRAVERSE_USER_AGENT", "Traverse/Test")

    args = build_parser().parse_args([])
    config = load_config(args)

    assert config.cache_path == traverse_cache
    assert config.user_agent == "Traverse/Test"
