from __future__ import annotations

import pytest

from wiki_agent.errors import WikiAgentError
from wiki_agent.fetcher import FetchResult
from wiki_agent.providers.arxiv import ArxivAdapter
from wiki_agent.providers.imdb import ImdbAdapter
from wiki_agent.providers.web import WebAdapter


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
        "https://help.imdb.com/article/imdb/general-information/what-is-imdb/ABC",
        "https://www.imdb.com/title/tt0111161/",
    ]
    assert result["links"][1]["page_type"] == "external"
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


def test_web_adapter_parses_public_https_and_external_links(monkeypatch) -> None:
    adapter = WebAdapter()
    source = fetched(
        "https://papers.example.org/article?id=7",
        b"""
        <html><head><title>Research paper</title></head><body><main>
          <h1>Research paper</h1>
          <p>A useful result with <a href="/references">references</a>.</p>
          <p><a href="https://data.example.net/result">Supporting data</a></p>
        </main></body></html>
        """,
        "web",
    )
    monkeypatch.setattr(
        "wiki_agent.providers.web.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    adapter.validate_network_destination(source.url)
    result = adapter.traverse(source, 10)

    assert result["title"] == "Research paper"
    assert [link["href"] for link in result["links"]] == [
        "https://papers.example.org/references",
        "https://data.example.net/result",
    ]
    assert [link["page_type"] for link in result["links"]] == ["article", "external"]

    external_only = adapter.traverse(source, 10, namespaces=["external"])

    assert [link["href"] for link in external_only["links"]] == [
        "https://data.example.net/result"
    ]


def test_web_adapter_honors_html_charset() -> None:
    adapter = WebAdapter()
    source = FetchResult(
        url="https://example.org/article",
        body="<html><body><main><h1>Création</h1><p>Collège.</p></main></body></html>".encode(),
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="text/html; charset=UTF-8",
        provider="web",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    assert result["title"] == "Création"
    assert result["lead"] == "Collège."


def test_web_adapter_reads_pdf_text(monkeypatch) -> None:
    adapter = WebAdapter()
    source = FetchResult(
        url="https://example.org/paper.pdf",
        body=b"%PDF-test",
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/pdf",
        provider="web",
    )
    monkeypatch.setattr(
        adapter,
        "_pdf",
        lambda fetch: (
            "Innovation Paper",
            "Introduction\n\nReferences\nAghion, P. 1992. A Model of Growth.",
            ["Introduction", "References\nAghion, P. 1992. A Model of Growth."],
        ),
    )

    result = adapter.read(source, output_format="plain")

    assert result["title"] == "Innovation Paper"
    assert "References" in result["text"]
    assert result["meta"]["media_type"] == "pdf"
    assert result["html"] is None


def test_web_adapter_pdf_traverse_honors_page_types(monkeypatch) -> None:
    adapter = WebAdapter()
    source = FetchResult(
        url="https://example.org/paper.pdf",
        body=b"%PDF-test",
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/pdf",
        provider="web",
    )
    monkeypatch.setattr(
        adapter,
        "_pdf",
        lambda fetch: (
            "Paper",
            "Data: https://example.net/data",
            ["Data: https://example.net/data"],
        ),
    )

    result = adapter.traverse(source, 10, page_types=["article"])

    assert result["links"] == []

    result = adapter.traverse(source, 10, namespaces=["article"])

    assert result["links"] == []


def test_web_adapter_limits_pdf_pages(monkeypatch) -> None:
    adapter = WebAdapter()
    source = FetchResult(
        url="https://example.org/paper.pdf",
        body=b"%PDF-test",
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/pdf",
        provider="web",
    )

    class OversizedPdf:
        pages = [None] * 501
        metadata = None

    monkeypatch.setattr(
        "wiki_agent.providers.web.PdfReader",
        lambda stream: OversizedPdf(),
    )

    with pytest.raises(WikiAgentError, match="page extraction limit"):
        adapter.read(source, output_format="plain")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/",
        "https://localhost/page",
        "https://127.0.0.1/page",
        "https://user@example.org/page",
        "https://example.org:8443/page",
    ],
)
def test_web_adapter_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(WikiAgentError):
        WebAdapter().validate_url(url)


def test_web_adapter_rejects_private_dns_results(monkeypatch) -> None:
    adapter = WebAdapter()
    monkeypatch.setattr(
        "wiki_agent.providers.web.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.5", 443))],
    )

    with pytest.raises(WikiAgentError, match="public network"):
        adapter.validate_network_destination("https://example.org/page")


def test_web_adapter_normalizes_idn_and_ipv6() -> None:
    adapter = WebAdapter()

    assert adapter.validate_url("https://éxample.org/paper") == (
        "https://xn--xample-9ua.org/paper"
    )
    assert adapter.validate_url("https://[2606:4700:4700::1111]/paper") == (
        "https://[2606:4700:4700::1111]/paper"
    )
    assert adapter.robots_url("https://[2606:4700:4700::1111]/paper") == (
        "https://[2606:4700:4700::1111]/robots.txt"
    )
    assert adapter.validate_url("https://example.org/search?q=café") == (
        "https://example.org/search?q=caf%C3%A9"
    )


def test_web_adapter_sanitizes_active_html() -> None:
    adapter = WebAdapter()
    source = fetched(
        "https://example.org/article",
        b"""
        <html><body><main>
          <meta http-equiv="refresh" content="0;url=https://evil.example">
          <h1 onclick="alert(1)">Paper</h1>
          <svg><a href="data:text/html,evil">active</a></svg>
          <p style="background:url(javascript:alert(1))">Text</p>
          <a href="data:text/html,evil">bad link</a>
          <a href="https://safe.example/page">safe link</a>
        </main></body></html>
        """,
        "web",
    )

    result = adapter.read(source, output_format="html")

    assert result["html"] is not None
    assert "<meta" not in result["html"]
    assert "<svg" not in result["html"]
    assert "onclick" not in result["html"]
    assert "style=" not in result["html"]
    assert "data:text/html" not in result["html"]
    assert 'href="https://safe.example/page"' in result["html"]
