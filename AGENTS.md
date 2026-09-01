# PurePath provider development

This repository implements a local MCP server for polite, user-directed
navigation of public hypertext. Prefer following links in server-rendered HTML
over search endpoints, private APIs, browser automation, or guessed URLs.

## Provider acceptance criteria

Do not implement a provider until all of these checks are complete:

1. Read the site's current terms from an authoritative URL. Distinguish
   assistive navigation from bulk scraping, data mining, archiving, model
   training, republication, and commercial data extraction. Do not proceed
   when the terms clearly prohibit automated access or the intended use.
2. Read `robots.txt` using the same public host the adapter will fetch. Record
   relevant disallowed paths, crawl delay, and sitemap locations. Robots
   permission is necessary but is not legal permission.
3. Verify the proposed navigation chain using real pages. Category, index,
   listing, and article or product links must be present in the initial
   response HTML unless the provider intentionally consumes a public XML, RSS,
   CSV, or PDF document.
4. Confirm the site does not require authentication, CAPTCHA circumvention,
   browser automation, a private endpoint, or a bot-protection bypass.
5. Identify a deterministic starting point such as a portal, A-Z directory,
   department page, archive, public feed, or sitemap. PurePath does not use
   site-search routes.

If policy language is ambiguous, document the ambiguity for the user and wait
for an explicit decision before implementation. Never work around a site's
technical refusal to serve the configured PurePath user agent.

## Choose the smallest adapter type

- Subclass `GenericHtmlAdapter` for ordinary HTML sites.
- Subclass `RetailHtmlAdapter` for same-origin category-to-product navigation
  with query stripping and Product JSON-LD metadata.
- Subclass `SiteAdapter` only when the site's parsing model is substantially
  different, as with Wikipedia.
- Add custom handling to an HTML adapter for explicitly supported public
  formats such as XML sitemaps, RSS feeds, or bounded CSV data.
- Leave unknown public HTTPS HTML and PDF pages to `WebAdapter`. A specialized
  domain must never fall through to the generic adapter.

Review nearby providers before adding helpers:

- `src/wiki_agent/providers/webmd.py` for strict query handling and synthesized
  directories.
- `src/wiki_agent/providers/stockanalysis.py` for XML sitemap traversal.
- `src/wiki_agent/providers/foxsports.py` for stable synthesized subdirectories
  and structured tables.
- `src/wiki_agent/providers/retail.py`, `ikea.py`, and `staples.py` for retail
  navigation.

## URL and route policy

Every specialized adapter must define:

- A unique lowercase `name`.
- `hosts` containing only accepted hosts.
- `protected_domains` containing the registrable domain. This prevents
  subdomains and trailing-dot variants from bypassing the provider through
  `WebAdapter`.
- A narrow `path_allowed` policy or explicit allowed and blocked path prefixes.
- A `page_type` mapping using the existing MCP values: `abstract`, `article`,
  `category`, `external`, `index`, `listing`, `other`, or `portal`.
- A stable `robots_url`.

Validation must fail closed:

- Require HTTPS.
- Reject credentials and non-default ports.
- Normalize trailing-dot hosts before comparison.
- Reject parent path segments and encoded path-separator tricks.
- Reject unsupported hosts before canonicalizing to another host.
- Block search, authentication, account, cart, checkout, subscription,
  application, write, upload, API, and other interactive routes.
- Prefer rejecting direct query URLs. If a site needs display-only parameters,
  allow only named keys, validate each value, reject duplicates, and continue
  to block search-like keys.
- Discovered links may have known tracking parameters removed before
  validation. Do not silently convert a directly requested search or filtered
  URL into another page.

Keep discovery same-origin unless outbound navigation is an intentional,
documented feature of that provider. Return canonical absolute URLs.

Do not synthesize content URLs merely because a pattern looks plausible.
Synthesis is appropriate only for a verified, stable directory structure such
as Fox Sports league subpages or WebMD's A-Z letters. Otherwise, return URLs
found in a fetched page, feed, or sitemap.

## Parsing behavior

Reuse `GenericHtmlAdapter` wherever possible. Configure `root_xpaths` so
navigation, cookie banners, footers, and unrelated chrome do not dominate
results.

Override only what the site requires:

- `title` when Open Graph or another stable metadata source is more reliable
  than the first `h1`.
- `custom_lead` to skip author boxes, advertisements, legal notices, or other
  repeated boilerplate.
- `metadata` for JSON-LD or stable page metadata.
- `traverse` for published directories, sitemaps, feeds, or synthesized hubs.
- `skim` and `read` when the provider exposes useful structured tables or a
  non-HTML format.
- `accepts_content_type` and `request_headers` only for formats the adapter
  actually handles.

Maintain the existing MCP result shapes. Add provider-specific information
inside established fields such as `infobox`, `tables`, link `context`, and
`meta`; do not invent incompatible top-level response formats.

Bound all parsing. Follow existing limits for response bytes, PDF pages, CSV
rows, table extraction, returned links, context length, and redirects.

## Registration and documentation

After creating `src/wiki_agent/providers/<name>.py`:

1. Import and instantiate the adapter in
   `src/wiki_agent/providers/registry.py`.
2. Place it before `WebAdapter`, which must remain the final fallback.
3. Add the provider to `src/wiki_agent/help_content.py` with:
   - supported URL patterns;
   - intended use;
   - blocked or unsupported behavior;
   - at least one realistic `traverse -> skim -> read` recipe when useful.
4. Update help-provider expectations in `tests/test_mcp_server.py`.

Keep `README.md` limited to installation and setup instructions. Provider
development guidance belongs in this file and runtime usage guidance belongs
in the MCP `help` response.

## Required tests

Add focused coverage to `tests/test_providers.py` for:

- Accepted canonical URLs and page-type classification.
- Search, query, API, account, write, and interactive route rejection.
- Wrong hosts, credentials, ports, parent paths, trailing dots, and protected
  subdomains.
- Tracking-query removal on discovered links, when applicable.
- Same-origin or explicitly allowed outbound-link behavior.
- Representative category/index/listing/article or product HTML.
- Provider-specific metadata, tables, sitemap, feed, or directory behavior.
- The protected-domain regression case so the generic fallback cannot weaken
  provider policy.

Add fetcher tests when behavior changes redirects, robots enforcement,
network-address validation, caching, throttling, or content-type handling.

Run the smallest relevant tests first, then the full suite:

```powershell
python -m pytest tests\test_providers.py tests\test_mcp_server.py -q
python -m pytest -q
git --no-pager diff --check
```

Do not add a new test, lint, or build tool solely for a provider.

## Live validation

After tests pass, use the repository's `PoliteFetcher` and provider registry
against representative live pages:

1. Fetch the deterministic starting page.
2. Confirm `traverse` returns real category or listing links with useful local
   context.
3. Follow a returned link rather than typing a predicted content URL.
4. Confirm a representative `skim` has the expected title, lead, metadata,
   sections, and tables.
5. Confirm an article or product `read` returns meaningful simplified text.
6. Check that a known blocked path fails and that robots state was loaded.
7. Remove temporary cache files created for validation.

Use the configured descriptive `PUREPATH_USER_AGENT`, honor the site's crawl
delay, and keep requests sequential and minimal. A live 403, CAPTCHA, robots
failure, empty client-rendered shell, or redirect into a blocked route is a
provider blocker, not an invitation to bypass the site.

## Definition of done

A provider is complete only when its policy decision is recorded in the work
summary, URL handling fails closed, parsing works on representative fixtures,
the domain cannot fall through to generic web, MCP help is updated, the full
test suite passes, and the real navigation chain works with the normal
PurePath fetcher.
