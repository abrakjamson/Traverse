# Traverse end-to-end evaluation

Date: 2026-08-31

Fifteen GPT-5.6 Luna evaluators tested Traverse using only its MCP tools. The
suite covered every provider and three cross-provider workflows. Evaluators
were required to start with `help`, follow returned links rather than inventing
URLs, report their call trace, and identify failures separately from bugs.

## Provider results

| Provider | Question | Result | Navigation trace |
|---|---|---|---|
| Wikipedia | Who won the 2025 Nobel economics prize, and for what contributions? | Answered correctly for Joel Mokyr, Philippe Aghion, and Peter Howitt. | Contents portals -> Society and social sciences -> Society portal -> Economics category -> Business and economics portal -> Nobel Prize in Economics -> laureate pages |
| IMDb Help | How does IMDb describe watch availability and video limitations? | Internal Help pages explained recommendations, Watchlists, and Scorecard video restrictions. Main IMDb watch pages remained unavailable under provider policy. | IMDb Help site index -> locally filtered Watch and video links -> recommendation FAQ and Title Scorecard |
| arXiv | Find a current cs.AI paper about agents or reasoning and summarize it. | Found and summarized "DS-Lighting: Making Agent Harnesses Explicit for Data-Science Automation." | cs archive -> cs.AI -> new listing -> returned abstract link |
| NerdWallet | What are the September 2026 Social Security payment dates? | Found the correct September 1, 3, 9, 16, and 23 schedule and recipient exceptions. | Public feed -> finance navigation -> Social Security hub -> payment-schedule article |
| NPR | Explain the latest major economic-indicator story in the business section. | Answered from an August 28 inflation and rate-expectations article. | Business section -> local inflation filter -> returned article -> skim/read |
| FRED | How did unemployment change from January through the latest 2026 observation? | Correctly calculated a decline from 4.3% to 4.1% through July. | Homepage -> categories -> Current Population Survey -> unemployment category -> UNRATE -> bounded CSV |
| StockAnalysis | How did MSFT change over the latest five sessions, and why? | Correctly calculated a $19.98 or 4.10% gain and followed linked company coverage with appropriate causality caveats. | Sitemap index -> stock sitemap -> MSFT history -> overview and returned news links |
| WebMD | Does xylitol affect cardiovascular risk? | The WebMD X directory had no xylitol destination, so the evaluator correctly declined to make a medical conclusion. | Health topics X directory -> A-Z hub checks |
| Fox Sports | Where do Barcelona and Rayo Vallecano stand in La Liga? | Answered: Barcelona first with 9 points, Rayo 18th with 1 point, an 8-point gap in the retrieved table. | La Liga hub -> synthesized standings link -> structured standings table |
| IKEA | Compare the least expensive two-seat sofa and sleeper sofa. | Found GLOSTAD at $169 and FRIDHULT at $299, including availability and practical differences. | Products -> sofas -> two-seat and sleeper subcategories -> returned product links |
| Staples | Compare the first reachable gel-pen products. | Reached the Pens listing and product pages with pack, price, and per-unit context. Initial results contained only one gel pen, so the evaluator avoided claiming a complete category-wide ranking. | Office Supplies -> Pens -> returned product link |
| Generic web | Follow a Wikipedia xylitol citation and assess cardiovascular evidence. | Successfully opened a Cochrane citation, but correctly reported that it addressed dental caries rather than cardiovascular outcomes. | Wikipedia portals -> nutrition -> sugar -> sugar alcohol -> xylitol -> external citation -> Cochrane |

## Cross-provider results

| Question | Result |
|---|---|
| Garmin Fenix 8 retailer price | The initial category traversal failed to expose the product. A user-supplied Staples product page revealed the correct Wearable Technology -> Smart Watches chain and a current structured price of $1,254.59. This exposed and led to a listing parser fix. |
| Love Island reunion and Dancing with the Stars winner | The reunion-specific availability could not be verified through allowed links. Wikipedia did establish platform context. The latest completed U.S. Dancing with the Stars season was answered as Robert Irwin and Witney Carson. |
| Dragon Ball Burger King meal and Dairy Queen fall menu | Neither current fact was reachable through permitted links. Relevant archival and official destinations were blocked by robots or lacked a current linked source, and the evaluator correctly refused to guess. |

## Bugs fixed

### Staples product discovery

Some Staples category pages render product placeholders as HTML while placing
the public product records in the page's `__NEXT_DATA__` script. Anchor-only
traversal therefore missed products that were visibly available on the site,
including the Garmin Fenix 8.

The Staples adapter now extracts bounded product entries from that initial-page
JSON and merges them with normal category links. It returns the published
product URL, title, price, per-unit price, and rating context while continuing
to reject search and query URLs.

### NerdWallet wrapped sections

NerdWallet article headings are frequently wrapped in nested single-child
containers, with the section content in following sibling blocks. The generic
heading parser treated those sections as empty, causing September payment dates
to disappear from `skim` summaries and `read` text.

The NerdWallet adapter now recognizes those heading boundaries, includes the
following content blocks, removes script and navigation text from full reads,
and classifies major hubs as indexes.

### arXiv listing summaries

arXiv listings use HTML definition lists. Generic summaries and full text
ignored `dl`, `dt`, and `dd` content even though the links were discoverable.
Those elements are now included in text and summary extraction.

## Working well

- The `traverse -> skim -> read` workflow consistently minimized unnecessary
  full-page reads.
- Local `query` filtering was effective without invoking site-search routes.
- Wikipedia portals, FRED categories, StockAnalysis sitemaps, WebMD's A-Z
  directory, Fox Sports synthesized hubs, and retail category trees all
  provided deterministic starting points.
- Robots enforcement, crawl delays, canonical URLs, redirect checks, and
  protected-domain routing failed closed.
- Structured tables and Product JSON-LD made numerical and retail questions
  substantially more reliable.
- Evaluators generally distinguished unavailable evidence from a negative
  factual conclusion and did not fabricate answers.

## Needs improvement

- Large `help`, `skim`, `read`, sitemap, and portal results can exceed the
  caller's inline display budget. Evaluators succeeded by using local queries,
  section selection, and offsets, but concise result modes or explicit output
  budgets would improve usability.
- Generic outbound pages vary substantially. Some pages were dominated by site
  chrome or produced weak semantic summaries even though the fetch succeeded.
  Provider-specific adapters remain preferable for frequently used domains.
- External citation traversal can be noisy because one source may expose DOI,
  PubMed, archive, and metadata variants. Better duplicate grouping would
  reduce pagination.
- `read.text` intentionally omits structured table rows when they are returned
  in `tables`. Agents need clearer guidance to inspect both fields.
- Search-free navigation cannot answer every current commercial or
  entertainment question. Missing linked archives or blocked official sites
  should remain explicit limitations rather than trigger URL guessing or
  search-endpoint use.

## Overall assessment

Traverse reliably answered the questions that matched a provider's published
directory structure and failed safely when the required fact was not linked or
permitted. The strongest workflows were FRED, StockAnalysis, Fox Sports, IKEA,
Staples, NPR, arXiv abstracts, and Wikipedia orientation. The main remaining
work is response-size ergonomics and better extraction for unfamiliar generic
web layouts, not basic provider routing or politeness enforcement.
