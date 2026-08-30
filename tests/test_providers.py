from __future__ import annotations

import pytest

from wiki_agent.errors import WikiAgentError
from wiki_agent.fetcher import FetchResult
from wiki_agent.providers.arxiv import ArxivAdapter
from wiki_agent.providers.imdb import ImdbAdapter


def fetched(url: str, body: bytes, provider: str) -> FetchResult:
    return FetchResult(
        url=url,
        body=body,
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="text/html",
        provider=provider,
    )


def test_imdb_traverse_keeps_help_articles_and_blocks_search() -> None:
    adapter = ImdbAdapter()
    source = fetched(
        "https://help.imdb.com/article/imdb/general-information/imdb-site-index/GNCX7BHNSPBTFALQ",
        b"""
        <html><head><title>IMDb | Help</title></head><body>
          <div class="a-section content_container"><a href="/login">Login</a></div>
          <div id="article_content" class="article_content">
            <h1>IMDb Site Index</h1>
            <p>Browse IMDb help topics and site destinations.</p>
            <p><a href="/article/imdb/general-information/what-is-imdb/ABC?ref_=index">What is IMDb?</a></p>
            <p><a href="/search/">Search help</a></p>
            <p><a href="https://www.imdb.com/title/tt0111161/">A title</a></p>
          </div>
        </body></html>
        """,
        "imdb",
    )

    result = adapter.traverse(source, 20)
    skim = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    assert result["title"] == "IMDb Site Index"
    assert skim["lead"] == "Browse IMDb help topics and site destinations."
    assert [link["href"] for link in result["links"]] == [
        "https://help.imdb.com/article/imdb/general-information/what-is-imdb/ABC"
    ]
    with pytest.raises(WikiAgentError, match="blocked"):
        adapter.validate_url("https://help.imdb.com/search/?q=movie")
    with pytest.raises(WikiAgentError, match="not supported"):
        adapter.validate_url("https://www.imdb.com/title/tt0111161/")


def test_arxiv_traverse_blocks_search_api_and_pdf() -> None:
    adapter = ArxivAdapter()
    source = fetched(
        "https://arxiv.org/",
        b"""
        <html><head><title>arXiv.org e-Print archive</title></head><body><main>
          <h2>Computer Science</h2>
          <a href="/archive/cs">Archive</a>
          <a href="/list/cs/new?skip=0&amp;show=25">New papers</a>
          <a href="/search/?query=agents">Search</a>
          <a href="/api/query">API</a>
          <a href="/pdf/2401.00001">PDF</a>
        </main></body></html>
        """,
        "arxiv",
    )

    result = adapter.traverse(source, 20)

    assert [link["href"] for link in result["links"]] == [
        "https://arxiv.org/archive/cs",
        "https://arxiv.org/list/cs/new?skip=0&show=25",
    ]
    for blocked in (
        "https://arxiv.org/search/?query=agents",
        "https://arxiv.org/find/all/1/all:+agents/0/1/0/all/0/1",
        "https://arxiv.org/api/query",
        "https://arxiv.org/pdf/2401.00001",
    ):
        with pytest.raises(WikiAgentError, match="blocked"):
            adapter.validate_url(blocked)


def test_arxiv_abstract_extracts_metadata_and_abstract() -> None:
    adapter = ArxivAdapter()
    source = fetched(
        "https://arxiv.org/abs/2401.00001",
        b"""
        <html><head><title>[2401.00001] Modular Agents</title></head><body><main>
          <h1 class="title">Title: Modular Agents</h1>
          <div class="authors">Authors: Ada Example, Lin Example</div>
          <blockquote class="abstract">Abstract: A modular agent architecture.</blockquote>
          <div class="subjects">Subjects: Artificial Intelligence (cs.AI)</div>
          <div class="submission-history">Submitted 1 January 2024</div>
        </main></body></html>
        """,
        "arxiv",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    assert result["title"] == "Modular Agents"
    assert result["lead"] == "A modular agent architecture."
    assert result["meta"]["provider"] == "arxiv"
    assert result["meta"]["page_type"] == "abstract"
    assert result["infobox"]["fields"] == [
        {"key": "Authors", "value": "Authors: Ada Example, Lin Example"},
        {"key": "Subjects", "value": "Subjects: Artificial Intelligence (cs.AI)"},
        {"key": "Submission history", "value": "Submitted 1 January 2024"},
    ]
