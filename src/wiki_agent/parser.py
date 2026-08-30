from __future__ import annotations

import re
import urllib.parse
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from lxml import etree, html

from .errors import WikiAgentError
from .fetcher import FetchResult
from .urls import BLOCKED_NAMESPACES, namespace_for_title


CITATION_RE = re.compile(r"\[(?:\d+|citation needed|note \d+)\]", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"(?<=[.!?])(?:[\"')\]]*)\s+(?=[A-Z0-9])")
IGNORED_TAGS = {"script", "style", "noscript", "svg", "math", "table"}


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    heading: str
    nodes: list[etree._Element]


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", CITATION_RE.sub("", value)).strip()


def element_text(node: etree._Element) -> str:
    clone = deepcopy(node)
    for child in clone.xpath(
        ".//script|.//style|.//noscript|.//svg|.//math|.//*[contains(concat(' ', normalize-space(@class), ' '), ' mw-editsection ')]|.//sup[contains(concat(' ', normalize-space(@class), ' '), ' reference ')]"
    ):
        child.drop_tree()
    return clean_text(clone.text_content())


def parse_document(body: bytes) -> html.HtmlElement:
    try:
        document = html.fromstring(body)
        document.make_links_absolute("https://en.wikipedia.org")
        return document
    except (etree.ParserError, ValueError) as exc:
        raise WikiAgentError("parse_error", "Unable to parse Wikipedia HTML") from exc


def page_title(document: html.HtmlElement) -> str:
    heading = document.xpath("//h1[@id='firstHeading'] | //h1[1]")
    if heading:
        return element_text(heading[0])
    titles = document.xpath("//title/text()")
    if titles:
        return clean_text(titles[0].removesuffix(" - Wikipedia"))
    raise WikiAgentError("parse_error", "Wikipedia page title was not found")


def content_root(document: html.HtmlElement) -> etree._Element:
    candidates = document.xpath(
        "//*[@id='mw-content-text']//*[contains(concat(' ', normalize-space(@class), ' '), ' mw-parser-output ')]"
    )
    if candidates:
        return candidates[0]
    candidates = document.xpath("//*[@id='mw-content-text'] | //main")
    if candidates:
        return candidates[0]
    raise WikiAgentError("parse_error", "Wikipedia content was not found")


def relative_wiki_href(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.hostname and parsed.hostname != "en.wikipedia.org":
        return None
    if not parsed.path.startswith("/wiki/"):
        return None
    raw_path_lower = parsed.path.lower()
    if "%2f" in raw_path_lower or "%5c" in raw_path_lower:
        return None
    decoded_path = urllib.parse.unquote(parsed.path)
    if any(segment == ".." for segment in decoded_path.split("/")):
        return None
    title = decoded_path.removeprefix("/wiki/")
    if not title:
        return None
    namespace = namespace_for_title(title)
    if namespace in BLOCKED_NAMESPACES:
        return None
    path = urllib.parse.quote(decoded_path, safe="/:()_")
    return path


def page_type(url: str) -> str:
    title = urllib.parse.unquote(urllib.parse.urlsplit(url).path.removeprefix("/wiki/")).lower()
    namespace = namespace_for_title(title)
    if namespace == "portal" or title.startswith("wikipedia:contents/portals"):
        return "portal"
    if namespace == "category":
        return "category"
    if namespace == "main":
        return "article"
    return "other"


def link_page_type(href: str) -> str:
    return page_type(f"https://en.wikipedia.org{href}")


def link_namespace(href: str) -> str:
    title = urllib.parse.unquote(urllib.parse.urlsplit(href).path.removeprefix("/wiki/"))
    return namespace_for_title(title)


def heading_for_wrapper(wrapper: etree._Element) -> etree._Element | None:
    headings = wrapper.xpath(
        "./h2 | ./h3 | ./h4 | ./h5 | ./h6 | "
        "./div[contains(concat(' ', normalize-space(@class), ' '), ' mw-heading ')]/"
        "*[self::h2 or self::h3 or self::h4 or self::h5 or self::h6]"
    )
    return headings[0] if headings else None


def section_from_wrapper(wrapper: etree._Element, *, lead: bool = False) -> Section:
    heading_node = heading_for_wrapper(wrapper)
    if lead:
        section_id = "lead"
        heading = "Lead"
    elif heading_node is None:
        section_id = wrapper.get("id") or "untitled_section"
        heading = "Untitled section"
    else:
        headline = heading_node.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' mw-headline ')]"
        )
        target = headline[0] if headline else heading_node
        heading = element_text(target)
        section_id = heading_node.get("id") or target.get("id") or re.sub(
            r"\W+", "_", heading
        ).strip("_")
    nodes = [
        child
        for child in wrapper
        if isinstance(child.tag, str)
        and child.tag.lower() != "section"
        and heading_for_wrapper(child) is None
    ]
    return Section(section_id, heading, nodes)


def iter_sections(root: etree._Element) -> list[Section]:
    wrapped_sections = root.xpath("./section")
    if wrapped_sections:
        sections: list[Section] = []

        def append_wrapped(wrapper: etree._Element, *, lead: bool = False) -> None:
            sections.append(section_from_wrapper(wrapper, lead=lead))
            for nested in wrapper.xpath("./section"):
                append_wrapped(nested)

        for index, wrapper in enumerate(wrapped_sections):
            append_wrapped(wrapper, lead=index == 0 and heading_for_wrapper(wrapper) is None)
        return sections

    sections: list[Section] = []
    current_heading = "Lead"
    current_id = "lead"
    current_nodes: list[etree._Element] = []

    def append_current() -> None:
        if current_nodes or current_heading != "Lead":
            sections.append(Section(current_id, current_heading, current_nodes.copy()))

    for child in root:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        heading_node: etree._Element | None = None
        if tag in {"h2", "h3"}:
            heading_node = child
        elif tag == "div" and "mw-heading" in (child.get("class") or "").split():
            headings = child.xpath("./h2 | ./h3")
            heading_node = headings[0] if headings else None
        if heading_node is not None:
            append_current()
            headline = heading_node.xpath(
                ".//*[contains(concat(' ', normalize-space(@class), ' '), ' mw-headline ')]"
            )
            target = headline[0] if headline else heading_node
            current_heading = element_text(target)
            current_id = heading_node.get("id") or target.get("id") or re.sub(
                r"\W+", "_", current_heading
            ).strip("_")
            current_nodes = []
        else:
            current_nodes.append(child)
    append_current()
    return sections


def sentence_for_anchor(anchor: etree._Element) -> str:
    block = anchor
    remaining_levels = 5
    while (
        block.getparent() is not None
        and block.tag not in {"p", "li", "dd", "td"}
        and remaining_levels > 0
    ):
        block = block.getparent()
        remaining_levels -= 1
    anchor_text = clean_text(anchor.text_content())
    text = element_text(block) if block.tag in {"p", "li", "dd", "td"} else anchor_text
    sentences = SENTENCE_RE.split(text)
    return next((sentence for sentence in sentences if anchor_text and anchor_text in sentence), text)


def extract_links(nodes: Iterable[etree._Element], limit: int) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in nodes:
        anchors = [node] if node.tag == "a" else node.xpath(".//a[@href]")
        for anchor in anchors:
            href = relative_wiki_href(anchor.get("href"))
            text = clean_text(anchor.text_content())
            if not href or not text or href in seen:
                continue
            seen.add(href)
            result.append({"href": href, "text": text, "sentence": sentence_for_anchor(anchor)})
            if len(result) >= limit:
                return result
    return result


def extract_infobox(root: etree._Element) -> dict[str, Any]:
    tables = root.xpath(".//table[contains(concat(' ', normalize-space(@class), ' '), ' infobox ')]")
    if not tables:
        return {"image": None, "fields": []}
    table = tables[0]
    images = table.xpath(".//img[1]/@src")
    image = urllib.parse.urljoin("https:", images[0]) if images else None
    fields: list[dict[str, str]] = []
    for row in table.xpath(".//tr"):
        keys = row.xpath("./th")
        values = row.xpath("./td")
        if keys and values:
            key = element_text(keys[0])
            value = element_text(values[0])
            if key and value:
                fields.append({"key": key, "value": value})
    return {"image": image, "fields": fields}


def lead_text(root: etree._Element, sections: list[Section] | None = None) -> str:
    parsed_sections = sections if sections is not None else iter_sections(root)
    if parsed_sections and parsed_sections[0].id == "lead":
        return "\n\n".join(
            text
            for node in parsed_sections[0].nodes
            if isinstance(node.tag, str) and node.tag.lower() == "p"
            if (text := element_text(node))
        )

    paragraphs: list[str] = []
    for child in root:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        if tag in {"h2", "h3"}:
            break
        if tag == "p":
            text = element_text(child)
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def table_section_id(table: etree._Element, sections: list[Section]) -> str:
    ancestors = set(table.iterancestors())
    for section in reversed(sections):
        if any(node is table or node in ancestors for node in section.nodes):
            return section.id
    return "lead"


def own_table_rows(table: etree._Element) -> list[etree._Element]:
    return table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")


def table_grid(
    table: etree._Element,
    max_rows: int,
    max_columns: int,
) -> list[tuple[etree._Element, list[str]]]:
    grid: list[tuple[etree._Element, list[str]]] = []
    pending_spans: dict[int, tuple[str, int]] = {}
    for row in own_table_rows(table)[:max_rows]:
        values: list[str] = []
        column = 0
        cells = row.xpath("./th | ./td")
        for cell in cells:
            while column in pending_spans:
                value, remaining = pending_spans.pop(column)
                values.append(value)
                if remaining > 1:
                    pending_spans[column] = (value, remaining - 1)
                column += 1
            if column >= max_columns:
                break
            value = element_text(cell)[:1000]
            try:
                colspan = max(1, min(int(cell.get("colspan", "1")), max_columns - column))
                rowspan = max(1, int(cell.get("rowspan", "1")))
            except ValueError:
                colspan = rowspan = 1
            for _ in range(colspan):
                values.append(value)
                if rowspan > 1:
                    pending_spans[column] = (value, rowspan - 1)
                column += 1
        final_column = min(max(pending_spans, default=column - 1), max_columns - 1)
        while column <= final_column:
            if column not in pending_spans:
                values.append("")
                column += 1
                continue
            value, remaining = pending_spans.pop(column)
            values.append(value)
            if remaining > 1:
                pending_spans[column] = (value, remaining - 1)
            column += 1
        if any(values):
            grid.append((row, values))
    return grid


def extract_tables(
    root: etree._Element,
    *,
    max_tables: int = 10,
    max_rows: int = 200,
    max_columns: int = 30,
    max_total_chars: int = 200_000,
) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    sections = iter_sections(root)
    remaining_chars = max_total_chars
    candidate_tables: list[etree._Element] = []
    for table in root.xpath(".//table"):
        classes = set((table.get("class") or "").split())
        if classes.intersection({"infobox", "navbox", "metadata", "ambox", "reflist"}):
            continue
        if any(
            set((ancestor.get("class") or "").split()).intersection(
                {"infobox", "navbox", "metadata", "ambox", "reflist"}
            )
            for ancestor in table.iterancestors("table")
        ):
            continue
        candidate_tables.append(table)

    tables_truncated = False
    for table in candidate_tables:
        if len(results) >= max_tables or remaining_chars <= 0:
            tables_truncated = True
            break
        grid = table_grid(table, max_rows, max_columns)
        if len(grid) < 2:
            continue
        size_truncated = False
        bounded_grid: list[list[str]] = []
        bounded_source_rows: list[etree._Element] = []
        for source_row, row in grid:
            bounded_row: list[str] = []
            for value in row:
                if remaining_chars <= 0:
                    size_truncated = True
                    break
                bounded_value = value[:remaining_chars]
                bounded_row.append(bounded_value)
                remaining_chars -= len(bounded_value)
                if len(bounded_value) < len(value):
                    size_truncated = True
                    break
            if bounded_row:
                bounded_grid.append(bounded_row)
                bounded_source_rows.append(source_row)
            if size_truncated:
                break
        grid = bounded_grid
        if len(grid) < 2:
            tables_truncated = tables_truncated or size_truncated
            break
        rows_in_table = own_table_rows(table)
        first_row = bounded_source_rows[0].xpath("./th | ./td")
        has_headers = bool(first_row) and all(cell.tag.lower() == "th" for cell in first_row)
        width = max(len(row) for row in grid)
        headers = grid[0] if has_headers else [f"column_{index + 1}" for index in range(width)]
        headers += [f"column_{index + 1}" for index in range(len(headers), width)]
        rows = grid[1:] if has_headers else grid
        rows = [row + [""] * (len(headers) - len(row)) for row in rows]
        captions = table.xpath("./caption")
        results.append(
            {
                "section_id": table_section_id(table, sections),
                "caption": element_text(captions[0]) if captions else None,
                "headers": headers,
                "rows": rows,
                "truncated": len(rows_in_table) > max_rows or size_truncated,
            }
        )
        tables_truncated = tables_truncated or size_truncated
    return results, tables_truncated


def category_names(document: html.HtmlElement) -> list[str]:
    categories: list[str] = []
    for anchor in document.xpath("//*[@id='mw-normal-catlinks']//a[contains(@href, '/wiki/Category:')]"):
        text = clean_text(anchor.text_content())
        if text and text != "Categories":
            categories.append(text)
    return categories


def see_also_links(sections: list[Section]) -> list[str]:
    links: list[str] = []
    for section in sections:
        if section.heading.lower() == "see also":
            links.extend(item["href"] for item in extract_links(section.nodes, 100))
    return links


def visible_text(root: etree._Element) -> str:
    parts: list[str] = []
    for node in root.xpath(".//h2|.//h3|.//h4|.//h5|.//h6|.//p|.//li"):
        if any(
            ancestor.tag in IGNORED_TAGS
            or "navbox" in (ancestor.get("class") or "").split()
            or "metadata" in (ancestor.get("class") or "").split()
            for ancestor in node.iterancestors()
        ):
            continue
        if node.tag == "li":
            clone = deepcopy(node)
            for nested_list in clone.xpath(".//ul | .//ol"):
                nested_list.drop_tree()
            text = element_text(clone)
        else:
            text = element_text(node)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def sanitized_html(root: etree._Element) -> str:
    clone = deepcopy(root)
    for node in clone.xpath(".//script|.//style|.//noscript|.//iframe|.//object|.//embed"):
        node.drop_tree()
    for node in clone.iter():
        for attribute in list(node.attrib):
            value = node.attrib[attribute].strip().lower()
            if attribute.lower().startswith("on") or (
                attribute.lower() in {"href", "src", "xlink:href"} and value.startswith("javascript:")
            ):
                del node.attrib[attribute]
    return etree.tostring(clone, encoding="unicode", method="html")


def traverse(
    fetch: FetchResult,
    max_links: int,
    *,
    query: str | None = None,
    page_types: list[str] | None = None,
    namespaces: list[str] | None = None,
    offset: int = 0,
    context_max_chars: int = 240,
) -> dict[str, Any]:
    document = parse_document(fetch.body)
    root = content_root(document)
    matching_links: list[dict[str, str]] = []
    seen: set[str] = set()
    normalized_query = query.casefold().strip() if query else None
    allowed_page_types = set(page_types or [])
    allowed_namespaces = {namespace.casefold().replace(" ", "_") for namespace in namespaces or []}
    for anchor in root.xpath(".//a[@href]"):
        href = relative_wiki_href(anchor.get("href"))
        text = clean_text(anchor.text_content())
        if not href or not text or href in seen:
            continue
        seen.add(href)
        context_node = anchor
        remaining_levels = 5
        while (
            context_node.getparent() is not None
            and context_node.tag not in {"p", "li", "td"}
            and remaining_levels > 0
        ):
            context_node = context_node.getparent()
            remaining_levels -= 1
        context = element_text(context_node) if context_node.tag in {"p", "li", "td"} else text
        target_page_type = link_page_type(href)
        namespace = link_namespace(href)
        if allowed_page_types and target_page_type not in allowed_page_types:
            continue
        if allowed_namespaces and namespace not in allowed_namespaces:
            continue
        if normalized_query and normalized_query not in f"{text} {href} {context}".casefold():
            continue
        matching_links.append(
            {
                "href": href,
                "text": text,
                "context": context[:context_max_chars],
                "page_type": target_page_type,
                "namespace": namespace,
            }
        )
        if len(matching_links) >= offset + max_links + 1:
            break
    has_more = len(matching_links) > offset + max_links
    links = matching_links[offset : offset + max_links]
    return {
        "url": fetch.url,
        "title": page_title(document),
        "fetched_at": fetch.fetched_at,
        "links": links,
        "meta": {
            "page_type": page_type(fetch.url),
            "provider": "wikipedia",
            "link_count": len(links),
            "offset": offset,
            "next_offset": offset + len(links) if has_more else None,
            "filters": {
                "query": query,
                "page_types": page_types,
                "namespaces": namespaces,
            },
            "cached": fetch.cached,
            "etag": fetch.etag,
            "last_modified": fetch.last_modified,
            "cache_control": "max-age=86400",
        },
    }


def skim(
    fetch: FetchResult,
    *,
    selected_sections: list[str] | None,
    max_links_per_section: int,
) -> dict[str, Any]:
    document = parse_document(fetch.body)
    root = content_root(document)
    all_sections = iter_sections(root)
    wanted = set(selected_sections or [])
    included = (
        [section for section in all_sections if section.id in wanted]
        if selected_sections is not None
        else all_sections[:10]
    )
    sections: list[dict[str, Any]] = []
    for section in included:
        text = "\n\n".join(
            element_text(node)
            for node in section.nodes
            if isinstance(node.tag, str) and node.tag.lower() in {"p", "li"} and element_text(node)
        )
        summary = SENTENCE_RE.split(text, maxsplit=1)[0] if text else None
        sections.append(
            {
                "id": section.id,
                "heading": section.heading,
                "summary": summary,
                "link_sentences": extract_links(section.nodes, max_links_per_section),
            }
        )
    text = visible_text(root)
    word_count = len(text.split())
    tables, tables_truncated = extract_tables(root)
    return {
        "url": fetch.url,
        "title": page_title(document),
        "fetched_at": fetch.fetched_at,
        "infobox": extract_infobox(root),
        "lead": lead_text(root, all_sections),
        "sections": sections,
        "tables": tables,
        "see_also": see_also_links(all_sections),
        "categories": category_names(document),
        "meta": {
            "word_count": word_count,
            "provider": "wikipedia",
            "total_sections": len(all_sections),
            "sections_truncated": selected_sections is None and len(all_sections) > len(included),
            "tables_truncated": tables_truncated,
            "reliability_hint": "high" if word_count >= 500 else "medium" if word_count >= 100 else "low",
            "cached": fetch.cached,
            "etag": fetch.etag,
            "last_modified": fetch.last_modified,
            "cache_control": "max-age=86400",
        },
    }


def read(fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
    document = parse_document(fetch.body)
    root = content_root(document)
    skim_result = skim(fetch, selected_sections=None, max_links_per_section=10)
    read_skim = {key: value for key, value in skim_result.items() if key != "tables"}
    text = visible_text(root)
    html_output = sanitized_html(root) if output_format == "html" else None
    return {
        "url": fetch.url,
        "title": page_title(document),
        "fetched_at": fetch.fetched_at,
        "text": text,
        "html": html_output,
        "skim": read_skim,
        "tables": skim_result["tables"],
        "meta": {
            "word_count": len(text.split()),
            "provider": "wikipedia",
            "sections_returned": len(skim_result["sections"]),
            "cached": fetch.cached,
            "etag": fetch.etag,
            "last_modified": fetch.last_modified,
            "cache_control": "max-age=86400",
        },
    }
