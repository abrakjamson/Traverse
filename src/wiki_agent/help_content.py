from __future__ import annotations

from typing import Any


def build_help() -> dict[str, Any]:
    return {
        "server": "PurePath",
        "purpose": (
            "Polite, search-free browsing across structured knowledge, news, finance, "
            "and public HTTPS pages. PurePath follows links from known starting points, "
            "checks robots.txt, applies crawl delays, and rejects unsafe destinations."
        ),
        "recommended_workflow": [
            {
                "step": 1,
                "tool": "traverse",
                "when": "Discover and filter links from an index, portal, section, sitemap, feed, or article.",
            },
            {
                "step": 2,
                "tool": "skim",
                "when": "Evaluate a promising page using its lead, metadata, sections, and link context.",
            },
            {
                "step": 3,
                "tool": "read",
                "when": "Retrieve the full simplified text or sanitized HTML after choosing the page.",
            },
        ],
        "tools": {
            "help": {
                "purpose": "Return this usage guide without making a network request.",
                "parameters": {},
            },
            "traverse": {
                "purpose": "Return links and their local context with low bandwidth.",
                "parameters": {
                    "url": "Required absolute URL.",
                    "max_links": "1-200; defaults to 50.",
                    "cache_only": "Use only a cached response; fail if absent.",
                    "query": (
                        "Optional local filter applied to links already present on the page. "
                        "It does not call a site search endpoint."
                    ),
                    "page_types": (
                        "Optional subset of abstract, article, category, external, index, "
                        "listing, other, or portal."
                    ),
                    "namespaces": (
                        "Optional provider-specific link namespace filter. Use external to "
                        "follow outbound links exposed by a source page."
                    ),
                    "offset": "Zero-based offset for paging through discovered links.",
                    "context_max_chars": "0-2000; limits context returned with each link.",
                },
            },
            "skim": {
                "purpose": "Return a concise semantic overview and section-level link sentences.",
                "parameters": {
                    "url": "Required absolute URL.",
                    "sections": "Optional exact section IDs to include.",
                    "max_links_per_section": "0-100; defaults to 10.",
                    "cache_ttl_override": "Development-only cache TTL override in seconds.",
                },
            },
            "read": {
                "purpose": "Return full simplified content from the selected page.",
                "parameters": {
                    "url": "Required absolute URL.",
                    "format": "plain or sanitized html; defaults to plain.",
                },
            },
            "health": {
                "purpose": "Report liveness, providers, robots checks, and crawl-delay state.",
                "parameters": {},
            },
        },
        "supported_sites": [
            {
                "provider": "wikipedia",
                "sites": ["https://en.wikipedia.org/wiki/*"],
                "use_for": (
                    "Encyclopedic orientation, portals, categories, tables, citations, "
                    "and safe outbound links to primary sources."
                ),
                "notes": "Supported article-like namespaces only; query-string search is blocked.",
            },
            {
                "provider": "imdb",
                "sites": ["https://help.imdb.com/*"],
                "use_for": "IMDb product documentation, policies, features, and help topics.",
                "notes": (
                    "Only IMDb Help is supported. Main IMDb title and person pages remain "
                    "unavailable under the site's current robots policy."
                ),
            },
            {
                "provider": "arxiv",
                "sites": ["https://arxiv.org/*"],
                "use_for": "Browsing subject archives, date listings, abstracts, and HTML papers.",
                "notes": "Search, API, PDF, source, account, and authentication paths are blocked.",
            },
            {
                "provider": "nerdwallet",
                "sites": ["https://www.nerdwallet.com/*"],
                "use_for": (
                    "Consumer-finance explainers and discovery through WordPress sitemaps "
                    "or the public article feed."
                ),
                "notes": "Search parameters, search routes, APIs, and application flows are blocked.",
            },
            {
                "provider": "npr",
                "sites": ["https://www.npr.org/*"],
                "use_for": "News sections, dated stories, and live-update pages.",
                "notes": (
                    "Same-origin navigation only. Search and query URLs are blocked; use section "
                    "pages, known articles, or the live-update sitemap."
                ),
            },
            {
                "provider": "fred",
                "sites": ["https://fred.stlouisfed.org/*"],
                "use_for": (
                    "Economic and market series, release/category navigation, and bounded "
                    "fredgraph.csv observations."
                ),
                "notes": (
                    "Search is blocked. FRED is not a general source for individual stock-price history."
                ),
            },
            {
                "provider": "stockanalysis",
                "sites": ["https://stockanalysis.com/*"],
                "use_for": (
                    "Stock and ETF profiles, historical prices, financial tables, market "
                    "lists, and links to related coverage."
                ),
                "notes": (
                    "Use the sitemap to discover ticker URLs without guessing. Search, symbol "
                    "lookup, screeners, account pages, paid features, and all query URLs are blocked."
                ),
            },
            {
                "provider": "webmd",
                "sites": ["https://www.webmd.com/*"],
                "use_for": (
                    "A-to-Z health topic discovery, condition hubs, and educational health articles."
                ),
                "notes": (
                    "The health-topics index supports only pg=a through pg=z. Search, APIs, "
                    "sponsored routes, interactive tools, and other query URLs are blocked. "
                    "Content is informational and not a substitute for medical care."
                ),
            },
            {
                "provider": "foxsports",
                "sites": ["https://www.foxsports.com/*"],
                "use_for": (
                    "Assistive navigation of league hubs, scores, standings, schedules, "
                    "teams, statistics, and sports coverage."
                ),
                "notes": (
                    "League and competition subdirectories are synthesized so callers need "
                    "not discover them through the homepage. Search, account, subscription, "
                    "watch/live, and betting routes are blocked. Use is limited to interactive "
                    "browsing, not bulk archiving or model training."
                ),
            },
            {
                "provider": "ikea",
                "sites": ["https://www.ikea.com/us/en/*"],
                "use_for": (
                    "Navigating IKEA departments, rooms, categories, product listings, "
                    "and individual home-furnishing products."
                ),
                "notes": (
                    "US English pages only. Search, filters, comparison, account, cart, "
                    "checkout, order, planner, and other interactive routes are blocked."
                ),
            },
            {
                "provider": "staples",
                "sites": ["https://www.staples.com/*"],
                "use_for": (
                    "Navigating Staples departments and product categories to individual "
                    "office, school, technology, and furniture products."
                ),
                "notes": (
                    "Only department/category and product pages are supported. Search, APIs, "
                    "accounts, inventory services, checkout, and query URLs are blocked."
                ),
            },
            {
                "provider": "web",
                "sites": ["Other public HTTPS HTML and PDF URLs"],
                "use_for": (
                    "Following outbound citations and reading known public pages when no "
                    "specialized provider is available."
                ),
                "notes": (
                    "Requires a known URL, public DNS destination, and an accessible robots policy. "
                    "It does not provide web search."
                ),
            },
        ],
        "traversal_examples": [
            {
                "goal": "Move from a Wikipedia portal to a focused article.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://en.wikipedia.org/wiki/Portal:Science",
                            "query": "physics",
                            "page_types": ["portal", "article"],
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {
                            "url": "<href selected from traverse>",
                            "max_links_per_section": 5,
                        },
                    },
                    {
                        "tool": "read",
                        "arguments": {"url": "<same selected href>", "format": "plain"},
                    },
                ],
            },
            {
                "goal": "Follow a Wikipedia citation or other outbound source.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://en.wikipedia.org/wiki/Philippe_Aghion",
                            "namespaces": ["external"],
                            "query": "nobel",
                            "max_links": 25,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<public HTTPS href selected from traverse>"},
                    },
                    {
                        "tool": "read",
                        "arguments": {
                            "url": "<selected HTML or PDF source>",
                            "format": "plain",
                        },
                    },
                ],
            },
            {
                "goal": "Browse arXiv without using search.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://arxiv.org/archive/cs",
                            "query": "artificial intelligence",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "<archive or list href selected above>",
                            "page_types": ["abstract"],
                            "max_links": 50,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<https://arxiv.org/abs/... href>"},
                    },
                ],
            },
            {
                "goal": "Discover and read a NerdWallet consumer-finance article.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.nerdwallet.com/blog/feed/",
                            "query": "mortgage",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<article href selected from the feed>"},
                    },
                    {
                        "tool": "read",
                        "arguments": {"url": "<same article href>", "format": "plain"},
                    },
                ],
            },
            {
                "goal": "Browse NPR from a section page to a full story.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.npr.org/sections/business/",
                            "query": "economy",
                            "page_types": ["article"],
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<dated NPR article href>"},
                    },
                    {
                        "tool": "read",
                        "arguments": {"url": "<same article href>", "format": "plain"},
                    },
                ],
            },
            {
                "goal": "Read a bounded date range from a FRED series.",
                "calls": [
                    {
                        "tool": "skim",
                        "arguments": {"url": "https://fred.stlouisfed.org/series/SP500"},
                    },
                    {
                        "tool": "read",
                        "arguments": {
                            "url": (
                                "https://fred.stlouisfed.org/graph/fredgraph.csv"
                                "?id=SP500&cosd=2026-08-01&coed=2026-08-31"
                            ),
                            "format": "plain",
                        },
                    },
                ],
            },
            {
                "goal": "Discover a stock ticker and read its historical prices.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://stockanalysis.com/sitemap.xml",
                            "query": "stocks",
                            "max_links": 10,
                        },
                    },
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "<stocks sitemap href selected above>",
                            "query": "msft history",
                            "max_links": 10,
                        },
                    },
                    {
                        "tool": "read",
                        "arguments": {
                            "url": "<ticker history href selected above>",
                            "format": "plain",
                        },
                    },
                ],
            },
            {
                "goal": "Browse WebMD from an A-to-Z topic directory.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.webmd.com/a-to-z-guides/health-topics?pg=a",
                            "query": "allerg",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<condition or topic hub selected above>"},
                    },
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "<same topic hub>",
                            "query": "<specific subtopic>",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "read",
                        "arguments": {"url": "<article selected above>", "format": "plain"},
                    },
                ],
            },
            {
                "goal": "Navigate directly from a Fox Sports league hub to structured data.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.foxsports.com/nfl",
                            "page_types": ["listing"],
                            "max_links": 10,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {
                            "url": "<scores, standings, schedule, teams, or stats href>"
                        },
                    },
                    {
                        "tool": "read",
                        "arguments": {
                            "url": "<same selected subpage>",
                            "format": "plain",
                        },
                    },
                ],
            },
            {
                "goal": "Browse IKEA from the product directory to an individual item.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.ikea.com/us/en/cat/products-products/",
                            "query": "furniture",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "<category href selected above>",
                            "page_types": ["listing", "article"],
                            "max_links": 30,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<product href selected above>"},
                    },
                ],
            },
            {
                "goal": "Browse Staples from a department to an individual product.",
                "calls": [
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "https://www.staples.com/Office-Supplies/cat_SC1",
                            "query": "pens",
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "traverse",
                        "arguments": {
                            "url": "<category href selected above>",
                            "page_types": ["article"],
                            "max_links": 20,
                        },
                    },
                    {
                        "tool": "skim",
                        "arguments": {"url": "<product href selected above>"},
                    },
                ],
            },
        ],
        "operating_rules": [
            "Start from a known URL or a link returned by traverse; PurePath intentionally has no search tool.",
            "Prefer traverse, then skim, then read to minimize bandwidth and unnecessary requests.",
            "A traverse query filters the fetched page locally and never authorizes a blocked search route.",
            "Use returned canonical href values rather than constructing provider URLs when possible.",
            "Robots denials, redirects to unsafe destinations, private-network targets, and unsupported paths fail closed.",
        ],
    }
