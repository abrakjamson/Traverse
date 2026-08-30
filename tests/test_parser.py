from __future__ import annotations

from wiki_agent.fetcher import FetchResult
from wiki_agent.parser import read, skim, traverse


HTML = b"""
<!doctype html>
<html>
  <head><title>Quantum tunnelling - Wikipedia</title></head>
  <body>
    <h1 id="firstHeading">Quantum tunnelling</h1>
    <main id="mw-content-text">
      <div class="mw-parser-output">
        <section id="lead-wrapper">
          <table class="infobox">
            <tr><th>Field</th><td>Quantum mechanics</td></tr>
            <tr><td><img src="//upload.wikimedia.org/example.png"></td></tr>
          </table>
          <p>Quantum tunnelling is a quantum effect <sup class="reference">[1]</sup>
            involving a <a href="/wiki/Potential_barrier">potential barrier</a>.</p>
        </section>
        <section id="mechanism-wrapper">
          <div class="mw-heading mw-heading2"><h2 id="Mechanism">Mechanism</h2></div>
          <p>A particle encountering a <a href="/wiki/Barrier_potential">barrier potential</a>
            may tunnel through it. This is important.</p>
          <table class="wikitable">
            <caption>Barrier observations</caption>
            <thead><tr><th>Year</th><th>Count</th></tr></thead>
            <tbody>
              <tr><td>1976</td><td>10</td></tr>
              <tr><td>1993</td><td>27</td></tr>
            </tbody>
          </table>
          <table class="infobox"><tr><td><table><tr><td>ignored</td></tr><tr><td>nested</td></tr></table></td></tr></table>
          <section id="history-wrapper">
            <div class="mw-heading mw-heading3"><h3 id="History">History</h3></div>
            <p>The theory developed over time.</p>
          </section>
        </section>
        <section id="see-also-wrapper">
          <div class="mw-heading mw-heading2"><h2 id="See_also">See also</h2></div>
          <ul><li><a href="/wiki/Tunnelling_(disambiguation)">Tunnelling</a></li></ul>
        </section>
        <script>alert("ignored")</script>
      </div>
    </main>
    <div id="mw-normal-catlinks">
      <a href="/wiki/Category:Quantum_mechanics">Quantum mechanics</a>
    </div>
  </body>
</html>
"""


def fetched() -> FetchResult:
    return FetchResult(
        url="https://en.wikipedia.org/wiki/Quantum_tunnelling",
        body=HTML,
        fetched_at="2026-08-29T00:00:00Z",
        cached=False,
        etag='"abc"',
        last_modified="Sat, 29 Aug 2026 00:00:00 GMT",
        content_type="text/html",
    )


def test_traverse_extracts_normalized_links() -> None:
    result = traverse(fetched(), 2, context_max_chars=30)

    assert result["title"] == "Quantum tunnelling"
    assert result["meta"]["page_type"] == "article"
    assert [link["href"] for link in result["links"]] == [
        "/wiki/Potential_barrier",
        "/wiki/Barrier_potential",
    ]
    assert all(len(link["context"]) <= 30 for link in result["links"])


def test_traverse_filters_and_paginates_links() -> None:
    first = traverse(fetched(), 1, query="barrier", page_types=["article"])
    second = traverse(fetched(), 1, query="barrier", page_types=["article"], offset=1)

    assert first["links"][0]["href"] == "/wiki/Potential_barrier"
    assert first["links"][0]["namespace"] == "main"
    assert first["meta"]["next_offset"] == 1
    assert second["links"][0]["href"] == "/wiki/Barrier_potential"
    assert second["meta"]["next_offset"] is None


def test_colon_in_article_title_is_not_treated_as_namespace() -> None:
    body = HTML.replace(
        b"</section>",
        b'<p><a href="/wiki/Dune:_Part_Two">Dune: Part Two</a></p></section>',
        1,
    )
    source = fetched()

    result = traverse(
        FetchResult(
            url=source.url,
            body=body,
            fetched_at=source.fetched_at,
            cached=source.cached,
            etag=source.etag,
            last_modified=source.last_modified,
            content_type=source.content_type,
        ),
        10,
        query="Dune",
        page_types=["article"],
        namespaces=["main"],
    )

    assert result["links"][0]["href"] == "/wiki/Dune:_Part_Two"
    assert result["links"][0]["page_type"] == "article"
    assert result["links"][0]["namespace"] == "main"


def test_skim_extracts_infobox_sections_and_link_sentences() -> None:
    result = skim(fetched(), selected_sections=["Mechanism"], max_links_per_section=5)

    assert result["infobox"]["image"] == "https://upload.wikimedia.org/example.png"
    assert result["infobox"]["fields"] == [{"key": "Field", "value": "Quantum mechanics"}]
    assert "[1]" not in result["lead"]
    assert result["sections"][0]["id"] == "Mechanism"
    assert result["sections"][0]["link_sentences"][0] == {
        "href": "/wiki/Barrier_potential",
        "text": "barrier potential",
        "sentence": "A particle encountering a barrier potential may tunnel through it.",
    }
    assert result["see_also"] == ["/wiki/Tunnelling_(disambiguation)"]
    assert result["categories"] == ["Quantum mechanics"]
    assert result["tables"] == [
        {
            "section_id": "Mechanism",
            "caption": "Barrier observations",
            "headers": ["Year", "Count"],
            "rows": [["1976", "10"], ["1993", "27"]],
            "truncated": False,
        }
    ]
    assert result["meta"]["total_sections"] == 4
    assert result["meta"]["sections_truncated"] is False


def test_read_returns_text_and_sanitized_html() -> None:
    result = read(fetched(), output_format="html")

    assert "Quantum tunnelling is a quantum effect" in result["text"]
    assert result["html"] is not None
    assert "<script" not in result["html"]
    assert [section["id"] for section in result["skim"]["sections"]] == [
        "lead",
        "Mechanism",
        "History",
        "See_also",
    ]
    assert result["meta"]["sections_returned"] == 4
    assert result["tables"][0]["headers"] == ["Year", "Count"]
    assert "tables" not in result["skim"]


def test_table_rowspan_preserves_non_contiguous_spans() -> None:
    body = HTML.replace(
        b"<tbody>",
        b"<tbody><tr><td colspan='2'>Combined</td><td rowspan='2'>Stable</td></tr>"
        b"<tr><td>Partial</td></tr>",
    )
    source = fetched()
    result = skim(
        FetchResult(
            url=source.url,
            body=body,
            fetched_at=source.fetched_at,
            cached=source.cached,
            etag=source.etag,
            last_modified=source.last_modified,
            content_type=source.content_type,
        ),
        selected_sections=None,
        max_links_per_section=0,
    )

    assert result["tables"][0]["rows"][0] == ["Combined", "Combined", "Stable"]
    assert result["tables"][0]["rows"][1] == ["Partial", "", "Stable"]
