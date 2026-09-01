from __future__ import annotations

from argparse import Namespace

import pytest

from wiki_agent.config import load_config
from wiki_agent.errors import WikiAgentError
from wiki_agent.fetcher import FetchResult
from wiki_agent.providers.arxiv import ArxivAdapter
from wiki_agent.providers.imdb import ImdbAdapter
from wiki_agent.providers.ikea import IkeaAdapter
from wiki_agent.providers.nerdwallet import NerdWalletAdapter
from wiki_agent.providers.npr import NprAdapter
from wiki_agent.providers.fred import FredAdapter
from wiki_agent.providers.foxsports import FoxSportsAdapter
from wiki_agent.providers.registry import build_registry
from wiki_agent.providers.stockanalysis import StockAnalysisAdapter
from wiki_agent.providers.staples import StaplesAdapter
from wiki_agent.providers.web import WebAdapter
from wiki_agent.providers.webmd import WebMdAdapter


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


def test_arxiv_listing_summarizes_definition_lists() -> None:
    adapter = ArxivAdapter()
    source = fetched(
        "https://arxiv.org/list/cs.AI/new",
        b"""
        <html><head><title>Artificial Intelligence</title></head><body><main>
          <h1>Artificial Intelligence</h1>
          <h3>New submissions</h3>
          <dl>
            <dt><a href="/abs/2608.28590">arXiv:2608.28590</a></dt>
            <dd>DS-Lighting: Making Agent Harnesses Explicit</dd>
          </dl>
        </main></body></html>
        """,
        "arxiv",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    section = next(item for item in result["sections"] if item["heading"] == "New submissions")
    assert section["summary"] == (
        "arXiv:2608.28590 DS-Lighting: Making Agent Harnesses Explicit"
    )
    assert section["link_sentences"][0]["href"] == (
        "https://arxiv.org/abs/2608.28590"
    )


def test_nerdwallet_blocks_search_routes_and_queries() -> None:
    adapter = NerdWalletAdapter()

    for url in (
        "https://www.nerdwallet.com/search/cards",
        "https://www.nerdwallet.com/wp-json/wp/v2/search?search=cards",
        "https://www.nerdwallet.com/credit-cards?s=travel",
    ):
        with pytest.raises(WikiAgentError, match="blocked|search"):
            adapter.validate_url(url)

    assert adapter.validate_url(
        "https://www.nerdwallet.com/credit-cards/best/travel?utm_source=test"
    ) == "https://www.nerdwallet.com/credit-cards/best/travel"
    assert adapter.request_headers() == {"Accept-Language": "en-US,en;q=0.9"}


def test_nerdwallet_traverses_wordpress_sitemap() -> None:
    adapter = NerdWalletAdapter()
    source = fetched(
        "https://www.nerdwallet.com/sitemaps/us/wp-sitemap-posts-articles-1.xml",
        b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://www.nerdwallet.com/banking/best/checking-accounts</loc>
            <lastmod>2026-08-28T00:00:00-07:00</lastmod>
          </url>
          <url>
            <loc>https://www.nerdwallet.com/finance/learn/make-a-budget</loc>
            <lastmod>2026-08-20T00:00:00-07:00</lastmod>
          </url>
        </urlset>
        """,
        "nerdwallet",
    )
    source = FetchResult(
        url=source.url,
        body=source.body,
        fetched_at=source.fetched_at,
        cached=source.cached,
        etag=source.etag,
        last_modified=source.last_modified,
        content_type="application/xml; charset=utf-8",
        provider=source.provider,
    )

    result = adapter.traverse(source, 10, query="checking")

    assert result["links"] == [
        {
            "href": "https://www.nerdwallet.com/banking/best/checking-accounts",
            "text": "checking accounts",
            "context": "Last modified: 2026-08-28T00:00:00-07:00",
            "page_type": "listing",
            "namespace": "nerdwallet",
        }
    ]
    assert result["meta"]["provider"] == "nerdwallet"


def test_nerdwallet_extracts_wordpress_json_ld_metadata() -> None:
    adapter = NerdWalletAdapter()
    source = fetched(
        "https://www.nerdwallet.com/finance/learn/make-a-budget",
        b"""
        <html><head>
          <link rel="canonical" href="https://www.nerdwallet.com/finance/learn/make-a-budget">
          <script type="application/ld+json">
            {
              "@type": "ItemList",
              "itemListElement": [{
                "@type": "Article",
                "author": {"name": "Nested Recommendation"}
              }]
            }
          </script>
          <script type="application/ld+json">
            {
              "@type": "Article",
              "url": "https://www.nerdwallet.com/finance/learn/make-a-budget",
              "author": [{"@type": "Person", "name": "Ada Nerd"}],
              "datePublished": "2026-01-02",
              "dateModified": "2026-08-20",
              "image": "https://www.nerdwallet.com/image.jpg"
            }
          </script>
        </head><body><main>
          <h1>How to Make a Budget</h1>
          <p>Ada Nerd is a personal finance writer at NerdWallet covering budgeting and saving.</p>
          <p>A practical budgeting guide.</p>
          <p>This practical budgeting guide explains how to organize expenses and build a plan that works over time.</p>
        </main></body></html>
        """,
        "nerdwallet",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    assert result["title"] == "How to Make a Budget"
    assert result["infobox"]["fields"] == [
        {"key": "Author", "value": "Ada Nerd"},
        {"key": "Published", "value": "2026-01-02"},
        {"key": "Updated", "value": "2026-08-20"},
    ]
    assert result["infobox"]["image"] == "https://www.nerdwallet.com/image.jpg"
    assert result["lead"].startswith("This practical budgeting guide")


def test_nerdwallet_extracts_wrapped_heading_sections() -> None:
    adapter = NerdWalletAdapter()
    source = fetched(
        "https://www.nerdwallet.com/retirement/learn/social-security-payment-schedule",
        b"""
        <html><head><title>Social Security Payment Schedule</title></head>
        <body><main><article>
          <div class="mb-4"><div id="september-dates">
            <h2>What day is my September 2026 payment coming?</h2>
          </div></div>
          <div class="mb-4"><span>September 1: SSI payments arrive.</span></div>
          <div class="mb-4"><span>September 9: Birthdays from 1 to 10.</span></div>
          <div class="mb-4"><div id="october-dates">
            <h2>What day is my October 2026 payment coming?</h2>
          </div></div>
          <div class="mb-4"><span>October 1: SSI payments arrive.</span></div>
        </article></main></body></html>
        """,
        "nerdwallet",
    )

    skim = adapter.skim(
        source,
        selected_sections=["september-dates"],
        max_links_per_section=5,
    )
    read = adapter.read(source, output_format="plain")

    assert skim["sections"][0]["summary"] == (
        "September 1: SSI payments arrive."
    )
    assert "September 9: Birthdays from 1 to 10." in read["text"]
    assert adapter.page_type(
        "https://www.nerdwallet.com/investing/hubs/social-security"
    ) == "index"


def test_nerdwallet_traverses_wordpress_feed() -> None:
    adapter = NerdWalletAdapter()
    source = FetchResult(
        url="https://www.nerdwallet.com/blog/feed/",
        body=b"""<?xml version="1.0"?>
        <rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
          <item>
            <title>Best Travel Cards</title>
            <link>https://www.nerdwallet.com/credit-cards/best/travel</link>
            <dc:creator>Ada Nerd</dc:creator>
            <pubDate>Fri, 28 Aug 2026 18:00:00 +0000</pubDate>
            <description>Compare current travel card options.</description>
          </item>
        </channel></rss>
        """,
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/rss+xml; charset=UTF-8",
        provider="nerdwallet",
    )

    result = adapter.traverse(source, 10, query="travel")

    assert result["links"] == [
        {
            "href": "https://www.nerdwallet.com/credit-cards/best/travel",
            "text": "Best Travel Cards",
            "context": (
                "Fri, 28 Aug 2026 18:00:00 +0000 | Ada Nerd | "
                "Compare current travel card options."
            ),
            "page_type": "article",
            "namespace": "nerdwallet",
        }
    ]
    skim = adapter.skim(
        source,
        selected_sections=["missing"],
        max_links_per_section=5,
    )
    assert skim["sections"] == []


def test_npr_blocks_search_and_query_urls() -> None:
    adapter = NprAdapter()

    for url in (
        "https://www.npr.org/templates/search/index.php",
        "https://www.npr.org/sections/news/?page=2",
        "https://www.npr.org/account/login",
    ):
        with pytest.raises(WikiAgentError, match="blocked|query"):
            adapter.validate_url(url)

    assert adapter.validate_url(
        "https://www.npr.org/2026/08/30/123456789/example-story"
    ) == "https://www.npr.org/2026/08/30/123456789/example-story"
    assert adapter.validate_url(
        "https://npr.org/2026/08/30/123456789/example-story"
    ) == "https://www.npr.org/2026/08/30/123456789/example-story"
    with pytest.raises(WikiAgentError, match="blocked"):
        adapter.validate_url("https://www.npr.org/newsletter/news")
    assert adapter.discovery_link("https://example.com/story", "https://www.npr.org/") is None


def test_npr_traverses_live_update_sitemap() -> None:
    adapter = NprAdapter()
    source = FetchResult(
        url="https://www.npr.org/live-updates/sitemap.xml",
        body=b"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap>
            <loc>https://www.npr.org/live-updates/sitemap-latest.xml</loc>
            <lastmod>2026-08-30T12:00:00-04:00</lastmod>
          </sitemap>
        </sitemapindex>
        """,
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="text/xml; charset=UTF-8",
        provider="npr",
    )

    result = adapter.traverse(source, 10, query="latest")

    assert result["links"] == [
        {
            "href": "https://www.npr.org/live-updates/sitemap-latest.xml",
            "text": "sitemap latest.xml",
            "context": "Last modified: 2026-08-30T12:00:00-04:00",
            "page_type": "listing",
            "namespace": "npr",
        }
    ]
    assert adapter.page_type(
        "https://www.npr.org/live-updates/example-event"
    ) == "article"


def test_npr_extracts_article_metadata() -> None:
    adapter = NprAdapter()
    source = fetched(
        "https://www.npr.org/2026/08/30/123456789/example-story",
        b"""
        <html><head><script type="application/ld+json">
          {
            "@type": "NewsArticle",
            "author": [{"name": "Ada Reporter"}],
            "datePublished": "2026-08-30T10:00:00-04:00",
            "image": {"url": "https://media.npr.org/image.jpg"}
          }
        </script></head><body><main><article>
          <h1>Example Story</h1>
          <p>This is a sufficiently detailed opening paragraph for an NPR news article used in parser testing.</p>
        </article></main></body></html>
        """,
        "npr",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=5)

    assert result["title"] == "Example Story"
    assert result["infobox"] == {
        "image": "https://media.npr.org/image.jpg",
        "fields": [
            {"key": "Author", "value": "Ada Reporter"},
            {"key": "Published", "value": "2026-08-30T10:00:00-04:00"},
        ],
    }


def test_fred_blocks_search_and_validates_csv_queries() -> None:
    adapter = FredAdapter()

    with pytest.raises(WikiAgentError, match="search"):
        adapter.validate_url("https://fred.stlouisfed.org/search?st=inflation")
    with pytest.raises(WikiAgentError, match="valid id"):
        adapter.validate_url("https://fred.stlouisfed.org/graph/fredgraph.csv")
    with pytest.raises(WikiAgentError, match="YYYY-MM-DD"):
        adapter.validate_url(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2026"
        )
    with pytest.raises(WikiAgentError, match="unsupported parameter"):
        adapter.validate_url(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&pageID=2"
        )
    with pytest.raises(WikiAgentError, match="must not be repeated"):
        adapter.validate_url(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&id=GDP"
        )

    assert adapter.validate_url(
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2026-08-01"
    ) == (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2026-08-01"
    )
    assert adapter.validate_url(
        "https://fred.stlouisfed.org/tags/series?t=markets&et=&pageID=2"
    ) == "https://fred.stlouisfed.org/tags/series?t=markets&et=&pageID=2"


def test_fred_parses_csv_observations() -> None:
    adapter = FredAdapter()
    source = FetchResult(
        url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
        body=(
            b"observation_date,SP500\n"
            b"2026-08-27,6500.25\n"
            b"2026-08-28,6512.75\n"
        ),
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/csv",
        provider="fred",
    )

    result = adapter.skim(source, selected_sections=None, max_links_per_section=0)

    assert result["title"] == "FRED series SP500"
    assert result["tables"] == [
        {
            "section_id": "observations",
            "caption": "Latest observations",
            "headers": ["observation_date", "SP500"],
            "rows": [["2026-08-27", "6500.25"], ["2026-08-28", "6512.75"]],
            "truncated": False,
        }
    ]
    assert result["meta"]["media_type"] == "csv"


def test_fred_read_wraps_csv_decode_errors() -> None:
    adapter = FredAdapter()
    source = FetchResult(
        url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
        body=b"\xff",
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/csv",
        provider="fred",
    )

    with pytest.raises(WikiAgentError, match="decode FRED CSV"):
        adapter.read(source, output_format="plain")


def test_stockanalysis_blocks_search_and_account_surfaces() -> None:
    adapter = StockAnalysisAdapter()

    for url in (
        "https://stockanalysis.com/search/?q=msft",
        "https://stockanalysis.com/symbol-lookup/",
        "https://stockanalysis.com/stocks/screener/",
        "https://stockanalysis.com/login/",
        "https://stockanalysis.com/e/example",
        "https://stockanalysis.com/p/example",
        "https://stockanalysis.com/stocks/msft/history/?period=year",
    ):
        with pytest.raises(WikiAgentError, match="blocked|query"):
            adapter.validate_url(url)

    assert adapter.validate_url(
        "https://www.stockanalysis.com/stocks/msft/history/"
    ) == "https://stockanalysis.com/stocks/msft/history/"
    assert adapter.validate_url(
        "https://stockanalysis.com/sitemaps/stocks/stocks2.xml"
    ) == "https://stockanalysis.com/sitemaps/stocks/stocks2.xml"


def test_stockanalysis_traverses_sitemap_for_ticker_history() -> None:
    adapter = StockAnalysisAdapter()
    source = FetchResult(
        url="https://stockanalysis.com/sitemaps/stocks/stocks2.xml",
        body=b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://stockanalysis.com/stocks/msft/</loc></url>
          <url><loc>https://stockanalysis.com/stocks/msft/history/</loc></url>
          <url><loc>https://stockanalysis.com/stocks/nvda/history/</loc></url>
        </urlset>
        """,
        fetched_at="2026-08-30T00:00:00Z",
        cached=False,
        etag=None,
        last_modified=None,
        content_type="application/xml",
        provider="stockanalysis",
    )

    result = adapter.traverse(source, 10, query="msft history")

    assert result["links"] == [
        {
            "href": "https://stockanalysis.com/stocks/msft/history/",
            "text": "stocks msft history",
            "context": "",
            "page_type": "listing",
            "namespace": "stockanalysis",
        }
    ]
    assert result["meta"]["provider"] == "stockanalysis"


def test_stockanalysis_extracts_historical_price_table_and_news_links() -> None:
    adapter = StockAnalysisAdapter()
    source = fetched(
        "https://stockanalysis.com/stocks/msft/history/",
        b"""
        <html><head><title>Microsoft Stock Price History</title></head><body><main>
          <h1>Microsoft Stock Price History</h1>
          <p>Historical price data is provided by S&amp;P Global Market Intelligence.</p>
          <h2>Historical Data</h2>
          <table>
            <thead><tr>
              <th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th>
            </tr></thead>
            <tbody>
              <tr><td>Aug 28, 2026</td><td>505.33</td><td>517.78</td><td>504.87</td><td>513.53</td></tr>
              <tr><td>Aug 27, 2026</td><td>494.88</td><td>506.48</td><td>490.08</td><td>505.06</td></tr>
            </tbody>
          </table>
          <h2>MSFT News</h2>
          <p><a href="https://example.com/msft-ai">Microsoft AI roadmap</a></p>
        </main></body></html>
        """,
        "stockanalysis",
    )

    skim = adapter.skim(source, selected_sections=None, max_links_per_section=5)
    read = adapter.read(source, output_format="plain")
    links = adapter.traverse(source, 10, namespaces=["external"])

    assert skim["tables"] == [
        {
            "section_id": "Historical_Data",
            "caption": None,
            "headers": ["Date", "Open", "High", "Low", "Close"],
            "rows": [
                ["Aug 28, 2026", "505.33", "517.78", "504.87", "513.53"],
                ["Aug 27, 2026", "494.88", "506.48", "490.08", "505.06"],
            ],
            "truncated": False,
        }
    ]
    assert read["tables"] == skim["tables"]
    assert "tables" not in read["skim"]
    assert links["links"][0]["href"] == "https://example.com/msft-ai"
    assert links["links"][0]["page_type"] == "external"


def test_foxsports_synthesizes_league_subdirectories() -> None:
    adapter = FoxSportsAdapter()
    source = fetched(
        "https://www.foxsports.com/nfl",
        b"""
        <html><head><meta property="og:title" content="NFL News and Scores"></head>
        <body><main><h1>NFL</h1><a href="/stories/nfl/example">Latest story</a></main></body></html>
        """,
        "foxsports",
    )

    result = adapter.traverse(source, 10, page_types=["listing"])

    assert [link["text"] for link in result["links"]] == [
        "Scores",
        "Standings",
        "Schedule",
        "Teams",
        "Stats",
    ]
    assert result["links"][0]["href"] == "https://www.foxsports.com/nfl/scores"


def test_foxsports_validates_display_queries_and_blocks_interactive_routes() -> None:
    adapter = FoxSportsAdapter()

    assert adapter.validate_url(
        "https://foxsports.com/nfl/schedule?seasonType=reg&week=2"
    ) == "https://www.foxsports.com/nfl/schedule?seasonType=reg&week=2"
    assert adapter.validate_url(
        "https://www.foxsports.com/sitemap.xml?type=football&page=2"
    ) == "https://www.foxsports.com/sitemap.xml?type=football&page=2"
    for url in (
        "https://www.foxsports.com/search/?q=nfl",
        "https://www.foxsports.com/live/",
        "https://www.foxsports.com/betting/nfl",
        "https://www.foxsports.com/nfl/schedule?q=bills",
        "https://www.foxsports.com/sitemap.xml?type=unknown",
    ):
        with pytest.raises(WikiAgentError, match="blocked|unsupported"):
            adapter.validate_url(url)


def test_foxsports_extracts_schedule_and_standings_tables() -> None:
    adapter = FoxSportsAdapter()
    source = fetched(
        "https://www.foxsports.com/nfl/standings",
        b"""
        <html><head><meta property="og:title" content="NFL Standings"></head><body><main>
          <h1>NFL PRESEASON STANDINGS</h1>
          <table>
            <thead><tr><th>Team</th><th>W</th><th>L</th></tr></thead>
            <tbody><tr><td>Buffalo Bills</td><td>3</td><td>0</td></tr></tbody>
          </table>
          <a href="/nfl/buffalo-bills-team">Buffalo Bills</a>
        </main></body></html>
        """,
        "foxsports",
    )

    skim = adapter.skim(source, selected_sections=None, max_links_per_section=5)
    read = adapter.read(source, output_format="plain")

    assert skim["title"] == "NFL Standings"
    assert skim["lead"].startswith("FOX Sports page for NFL Standings")
    assert skim["tables"][0]["headers"] == ["Team", "W", "L"]
    assert skim["tables"][0]["rows"] == [["Buffalo Bills", "3", "0"]]
    assert read["tables"] == skim["tables"]
    assert "tables" not in read["skim"]


def test_reserved_domains_cannot_fall_through_to_generic_web(tmp_path) -> None:
    config = load_config(
        Namespace(
            dev=True,
            ndjson=False,
            cache_path=tmp_path / "cache.sqlite3",
            base_url="https://en.wikipedia.org",
        )
    )
    registry = build_registry(config)

    for url in (
        "https://www.foxsports.com./nfl/",
        "https://m.foxsports.com/nfl/",
        "https://api.foxsports.com/data",
    ):
        assert registry.resolve(url).name == "foxsports"
    assert registry.resolve(
        "https://www.webmd.com./search/search_results/default.aspx?query=allergy"
    ).name == "webmd"
    assert registry.resolve("https://www.imdb.com/title/tt0111161/").name == "imdb"
    assert registry.resolve("https://www.ikea.com./us/en/search/?q=desk").name == "ikea"
    assert registry.resolve("https://api.staples.com/products").name == "staples"


def test_ikea_allows_us_navigation_and_blocks_interactive_routes() -> None:
    adapter = IkeaAdapter()

    assert adapter.validate_url(
        "https://ikea.com/us/en/cat/sofas-sectionals-fu003/"
    ) == "https://www.ikea.com/us/en/cat/sofas-sectionals-fu003/"
    assert adapter.page_type(
        "https://www.ikea.com/us/en/p/glostad-sofa-40595942/"
    ) == "article"
    for url in (
        "https://www.ikea.com/ca/en/cat/sofas-fu003/",
        "https://www.ikea.com/us/en/search/?q=sofa",
        "https://www.ikea.com/us/en/cat/sofas-fu003/?filter=color",
        "https://www.ikea.com/us/en/cart/",
        "https://www.ikea.com/us/en/checkout/",
        "https://www.ikea.com/us/en/profile/",
        "https://example.com/us/en/cat/sofas-fu003/",
        "https://user@www.ikea.com/us/en/cat/sofas-fu003/",
        "https://www.ikea.com:8443/us/en/cat/sofas-fu003/",
    ):
        with pytest.raises(
            WikiAgentError,
            match="blocked|query|not supported|credentials or a port",
        ):
            adapter.validate_url(url)


def test_ikea_traverses_categories_and_extracts_product_metadata() -> None:
    adapter = IkeaAdapter()
    source = fetched(
        "https://www.ikea.com/us/en/cat/sofas-sectionals-fu003/",
        b"""
        <html><head><meta property="og:title" content="Sofas &amp; Sectionals"></head>
        <body><main id="main-content">
          <h1>Sofas &amp; Sectionals</h1>
          <p>Find a comfortable sofa that fits your room, budget, and everyday needs.</p>
          <a href="/us/en/cat/two-seat-sofas-10668/">Two-seat sofas</a>
          <a href="/us/en/p/glostad-sofa-knisa-dark-gray-40595942/?utm_source=test">GLOSTAD sofa $169</a>
          <a href="/us/en/search/?q=sofa">Search</a>
          <a href="https://example.com/ad">Advertisement</a>
        </main></body></html>
        """,
        "ikea",
    )

    result = adapter.traverse(source, 10)

    assert [link["href"] for link in result["links"]] == [
        "https://www.ikea.com/us/en/cat/two-seat-sofas-10668/",
        "https://www.ikea.com/us/en/p/glostad-sofa-knisa-dark-gray-40595942/",
    ]
    assert [link["page_type"] for link in result["links"]] == ["listing", "article"]

    product = fetched(
        "https://www.ikea.com/us/en/p/glostad-sofa-knisa-dark-gray-40595942/",
        b"""
        <html><head>
          <meta property="og:title" content="GLOSTAD sofa">
          <script type="application/ld+json">
          {
            "@type": "Product",
            "brand": {"name": "IKEA"},
            "sku": "40595942",
            "image": ["https://www.ikea.com/glostad.jpg"],
            "offers": {
              "price": "169.00",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            }
          }
          </script>
        </head><body><main><h1>GLOSTAD sofa</h1>
          <p>A compact and comfortable dark gray sofa for everyday use.</p>
        </main></body></html>
        """,
        "ikea",
    )
    skim = adapter.skim(product, selected_sections=None, max_links_per_section=5)

    assert skim["infobox"] == {
        "image": "https://www.ikea.com/glostad.jpg",
        "fields": [
            {"key": "Brand", "value": "IKEA"},
            {"key": "SKU", "value": "40595942"},
            {"key": "Price", "value": "169.00"},
            {"key": "Currency", "value": "USD"},
            {"key": "Availability", "value": "InStock"},
        ],
    }


def test_staples_restricts_navigation_to_categories_and_products() -> None:
    adapter = StaplesAdapter()

    assert adapter.validate_url(
        "https://staples.com/Office-Supplies/cat_SC1"
    ) == "https://www.staples.com/Office-Supplies/cat_SC1"
    assert adapter.page_type(
        "https://www.staples.com/Office-Supplies/cat_SC1"
    ) == "index"
    assert adapter.page_type(
        "https://www.staples.com/Pens/cat_CL110001"
    ) == "listing"
    for url in (
        "https://www.staples.com/search?q=pens",
        "https://www.staples.com/Pens/cat_CL110001?page=2",
        "https://www.staples.com/cart",
        "https://www.staples.com/api/products",
        "https://www.staples.com/sbd/content/help/policies/terms_popup.html",
        "https://example.com/Pens/cat_CL110001",
        "https://user@www.staples.com/Pens/cat_CL110001",
        "https://www.staples.com:8443/Pens/cat_CL110001",
    ):
        with pytest.raises(
            WikiAgentError,
            match="blocked|query|not supported|credentials or a port",
        ):
            adapter.validate_url(url)


def test_staples_traverses_department_category_and_product_links() -> None:
    adapter = StaplesAdapter()
    source = fetched(
        "https://www.staples.com/Pens/cat_CL110001",
        b"""
        <html><head><meta property="og:title" content="Pens"></head><body><main>
          <h1>Pens</h1>
          <p>Shop pens for school, home, and office writing tasks.</p>
          <a href="/Writing-Supplies/cat_CL140899">Writing supplies</a>
          <div>
            <a href="/bic-round-stic-black-60-pack/product_442901?cid=promo">
              BIC Round Stic Xtra-Life Ballpoint Pen
            </a>
            Price is $6.99, regular price was $8.69.
          </div>
          <a href="/search?q=gel">Search</a>
          <a href="https://example.com/ad">Advertisement</a>
        </main></body></html>
        """,
        "staples",
    )

    result = adapter.traverse(source, 10)

    assert [link["href"] for link in result["links"]] == [
        "https://www.staples.com/Writing-Supplies/cat_CL140899",
        "https://www.staples.com/bic-round-stic-black-60-pack/product_442901",
    ]
    assert result["links"][1]["page_type"] == "article"
    assert "$6.99" in result["links"][1]["context"]


def test_staples_traverses_products_embedded_in_listing_json() -> None:
    adapter = StaplesAdapter()
    source = fetched(
        "https://www.staples.com/Smart-Watches/cat_CL211894",
        b"""
        <html><head><meta property="og:title" content="Smart Watches"></head>
        <body><main><h1>Smart Watches</h1>
          <a href="/Garmin-Smart-Watches/cat_CL211894/0060l">Garmin</a>
        </main>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "products": [{
              "itemId": "24678700",
              "url": "/garmin-fenix-8-pro/product_24678700",
              "title": "Garmin Fenix 8 Pro Multisport Smart Watch",
              "price": "$1,254.59",
              "pricePerUnit": "",
              "rating": 4.35,
              "ratingCount": 17
            }]
          }
        }
        </script></body></html>
        """,
        "staples",
    )

    result = adapter.traverse(source, 10, query="fenix")

    assert result["links"] == [
        {
            "href": "https://www.staples.com/garmin-fenix-8-pro/product_24678700",
            "text": "Garmin Fenix 8 Pro Multisport Smart Watch",
            "context": "$1,254.59 | 4.35 stars from 17 ratings",
            "page_type": "article",
            "namespace": "staples",
        }
    ]


def test_webmd_allows_only_topic_index_letter_queries() -> None:
    adapter = WebMdAdapter()

    assert adapter.validate_url(
        "https://webmd.com/a-to-z-guides/health-topics?pg=B"
    ) == "https://www.webmd.com/a-to-z-guides/health-topics?pg=b"
    assert adapter.validate_url(
        "https://www.webmd.com/allergies/default.htm"
    ) == "https://www.webmd.com/allergies/default.htm"
    for url in (
        "https://www.webmd.com/a-to-z-guides/health-topics?pg=all",
        "https://www.webmd.com/a-to-z-guides/health-topics?q=allergy",
        "https://www.webmd.com/allergies/default.htm?page=2",
        "https://www.webmd.com/search/search_results/default.aspx?query=allergy",
        "https://www.webmd.com/api/topics",
        "https://user:secret@www.webmd.com/allergies/default.htm",
        "https://www.webmd.com:8443/allergies/default.htm",
    ):
        with pytest.raises(
            WikiAgentError,
            match="blocked|single letter|pg parameter|credentials or a port",
        ):
            adapter.validate_url(url)


def test_webmd_topic_index_synthesizes_letters_and_filters_topics() -> None:
    adapter = WebMdAdapter()
    source = fetched(
        "https://www.webmd.com/a-to-z-guides/health-topics?pg=a",
        b"""
        <html><head><meta property="og:title" content="Health A-Z"></head><body><main>
          <h1>Health A-Z</h1>
          <h2>Topics Starting With A</h2>
          <a href="/allergies/default.htm">Allergies</a>
          <a href="/allergies/insect-stings">Allergies to Insect Stings</a>
          <a href="https://example.com/ad">External advertisement</a>
        </main></body></html>
        """,
        "webmd",
    )

    directory = adapter.traverse(source, 30, page_types=["listing"])
    allergies = adapter.traverse(source, 10, query="allerg")

    assert [link["text"] for link in directory["links"][:3]] == ["A", "B", "C"]
    assert directory["links"][1]["href"].endswith("?pg=b")
    assert [link["href"] for link in allergies["links"]] == [
        "https://www.webmd.com/allergies/default.htm",
        "https://www.webmd.com/allergies/insect-stings",
    ]
    assert all(link["namespace"] == "webmd" for link in allergies["links"])


def test_webmd_strips_tracking_queries_from_discovered_links() -> None:
    adapter = WebMdAdapter()
    source = fetched(
        "https://www.webmd.com/allergies/default.htm",
        b"""
        <html><body><main>
          <h1>Allergies</h1>
          <a href="/allergies/anaphylaxis?ecd=wnl_day">Anaphylaxis</a>
        </main></body></html>
        """,
        "webmd",
    )

    result = adapter.traverse(source, 10)

    assert result["links"][0]["href"] == "https://www.webmd.com/allergies/anaphylaxis"


def test_webmd_extracts_article_metadata_lead_tables_and_internal_links() -> None:
    adapter = WebMdAdapter()
    source = fetched(
        "https://www.webmd.com/allergies/example",
        b"""
        <html><head>
          <meta property="og:title" content="Understanding Allergies">
          <script type="application/ld+json">
          {
            "@type": "MedicalWebPage",
            "author": {"name": "WebMD Editorial Contributor"},
            "reviewedBy": {"name": "Ada Physician, MD"},
            "dateModified": "2026-08-30",
            "image": {"url": "https://img.webmd.com/allergies.jpg"}
          }
          </script>
        </head><body><main id="main-content">
          <h1>Find Doctors and Dentists Near You</h1>
          <h1>Understanding Allergies</h1>
          <p>Medically reviewed by Ada Physician, MD.</p>
          <p>Allergies happen when the immune system reacts to a normally harmless substance and can cause symptoms ranging from mild irritation to a serious emergency.</p>
          <h2>Symptoms</h2>
          <p>Symptoms vary by trigger and exposure.</p>
          <table><tr><th>Trigger</th><th>Example</th></tr><tr><td>Pollen</td><td>Grass</td></tr></table>
          <p><a href="/allergies/insect-stings">Insect sting allergies</a></p>
          <p><a href="https://example.com/ad">Advertisement</a></p>
        </main></body></html>
        """,
        "webmd",
    )

    skim = adapter.skim(source, selected_sections=None, max_links_per_section=5)
    read = adapter.read(source, output_format="plain")
    links = adapter.traverse(source, 10)

    assert skim["title"] == "Understanding Allergies"
    assert skim["lead"].startswith("Allergies happen when")
    assert skim["infobox"] == {
        "image": "https://img.webmd.com/allergies.jpg",
        "fields": [
            {"key": "Author", "value": "WebMD Editorial Contributor"},
            {"key": "Reviewed by", "value": "Ada Physician, MD"},
            {"key": "Updated", "value": "2026-08-30"},
        ],
    }
    assert skim["tables"][0]["headers"] == ["Trigger", "Example"]
    assert read["tables"] == skim["tables"]
    assert "tables" not in read["skim"]
    assert [link["href"] for link in links["links"]] == [
        "https://www.webmd.com/allergies/insect-stings"
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
