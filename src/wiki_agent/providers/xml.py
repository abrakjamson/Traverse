from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from ..errors import WikiAgentError
from .generic import clean_text


def parse_xml(body: bytes, label: str) -> etree._Element:
    try:
        return etree.fromstring(
            body,
            parser=etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                recover=False,
                huge_tree=False,
            ),
        )
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise WikiAgentError("parse_error", f"Unable to parse {label} XML") from exc


def parse_sitemap_entries(
    body: bytes,
    normalize: Callable[[str], str | None],
    label: str,
) -> list[dict[str, str]]:
    document = parse_xml(body, label)
    entries: list[dict[str, str]] = []
    for location in document.xpath("//*[local-name()='loc']"):
        href = normalize(clean_text(location.text or ""))
        if not href:
            continue
        parent = location.getparent()
        modified = ""
        if parent is not None:
            values = parent.xpath("./*[local-name()='lastmod']/text()")
            if values:
                modified = clean_text(values[0])
        entries.append({"href": href, "lastmod": modified})
    return entries
