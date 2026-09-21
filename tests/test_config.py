from __future__ import annotations

from wiki_agent.config import build_parser, load_config


def test_traverse_environment_takes_precedence(monkeypatch, tmp_path) -> None:
    traverse_cache = tmp_path / "traverse.sqlite3"
    purepath_cache = tmp_path / "purepath.sqlite3"
    monkeypatch.setenv("TRAVERSE_CACHE_PATH", str(traverse_cache))
    monkeypatch.setenv("PUREPATH_CACHE_PATH", str(purepath_cache))
    monkeypatch.setenv("TRAVERSE_USER_AGENT", "Traverse/Test")
    monkeypatch.setenv("PUREPATH_USER_AGENT", "PurePath/Test")

    args = build_parser().parse_args([])
    config = load_config(args)

    assert config.cache_path == traverse_cache
    assert config.user_agent == "Traverse/Test"


def test_purepath_environment_remains_compatible(monkeypatch, tmp_path) -> None:
    legacy_cache = tmp_path / "legacy.sqlite3"
    monkeypatch.delenv("TRAVERSE_CACHE_PATH", raising=False)
    monkeypatch.delenv("TRAVERSE_USER_AGENT", raising=False)
    monkeypatch.setenv("PUREPATH_CACHE_PATH", str(legacy_cache))
    monkeypatch.setenv("PUREPATH_USER_AGENT", "PurePath/Legacy")

    args = build_parser().parse_args([])
    config = load_config(args)

    assert config.cache_path == legacy_cache
    assert config.user_agent == "PurePath/Legacy"
