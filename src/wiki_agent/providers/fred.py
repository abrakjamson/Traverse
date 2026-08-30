from __future__ import annotations

import csv
import io
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from lxml import etree

from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, element_text

if TYPE_CHECKING:
    from ..fetcher import FetchResult


MAX_CSV_ROWS = 250_000
MAX_CSV_COLUMNS = 100


class FredAdapter(GenericHtmlAdapter):
    name = "fred"
    hosts = frozenset({"fred.stlouisfed.org"})
    root_xpaths = (
        "//*[@id='content-container']",
        "//main",
        "//*[@role='main']",
        "//body",
    )
    blocked_path_prefixes = (
        "/search",
        "/searchresults",
        "/graph/graph-landing.php",
        "/graph/image.php",
        "/graph/fredgraph.png",
        "/fred-glance-widget.php",
        "/seriesbeta",
    )
    allowed_query_keys = frozenset(
        {"id", "cosd", "coed", "pageID", "t", "et", "rid", "eid", "cid", "ob", "od"}
    )

    def path_allowed(self, path: str) -> bool:
        lowered = path.casefold()
        return not any(
            lowered == prefix or lowered.startswith(f"{prefix}/")
            for prefix in self.blocked_path_prefixes
        )

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if any(
            key.casefold() in {"q", "query", "search", "st", "text"}
            for key, _ in pairs
        ):
            raise WikiAgentError(
                "invalid_request",
                "search queries are blocked by the fred adapter",
            )
        is_csv_path = parsed.path.casefold() == "/graph/fredgraph.csv"
        path_query_keys = (
            {"id", "cosd", "coed"}
            if is_csv_path
            else {"pageID", "t", "et", "rid", "eid", "cid", "ob", "od"}
        )
        if is_csv_path and any(key not in path_query_keys for key, _ in pairs):
            raise WikiAgentError(
                "invalid_request",
                "FRED CSV contains an unsupported parameter",
            )
        filtered_pairs = [
            (key, item)
            for key, item in pairs
            if key in path_query_keys
        ]
        filtered_keys = [key for key, _ in filtered_pairs]
        if len(filtered_keys) != len(set(filtered_keys)):
            raise WikiAgentError(
                "invalid_request",
                "FRED query parameters must not be repeated",
            )
        for key, item in filtered_pairs:
            if key == "pageID" and not re.fullmatch(r"\d{1,5}", item):
                raise WikiAgentError("invalid_request", "pageID must be numeric")
            if key in {"rid", "eid", "cid"} and not re.fullmatch(r"\d{1,10}", item):
                raise WikiAgentError("invalid_request", f"{key} must be numeric")
            if key in {"t", "et"} and (
                len(item) > 200 or not re.fullmatch(r"[\w ,.()&+/-]*", item)
            ):
                raise WikiAgentError("invalid_request", f"{key} is invalid")
            if key == "od" and item not in {"", "asc", "desc"}:
                raise WikiAgentError("invalid_request", "od must be asc or desc")
            if key == "ob" and not re.fullmatch(r"[A-Za-z0-9_-]{0,30}", item):
                raise WikiAgentError("invalid_request", "ob is invalid")
        filtered_value = urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(filtered_pairs),
                "",
            )
        )
        normalized = super().validate_url(filtered_value)
        normalized_parts = urllib.parse.urlsplit(normalized)
        if normalized_parts.path == "/graph/fredgraph.csv":
            values = dict(urllib.parse.parse_qsl(normalized_parts.query))
            series_id = values.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_,.-]{1,500}", series_id):
                raise WikiAgentError(
                    "invalid_request",
                    "FRED CSV requests require a valid id parameter",
                )
            for key in ("cosd", "coed"):
                if key in values and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[key]):
                    raise WikiAgentError(
                        "invalid_request",
                        f"{key} must use YYYY-MM-DD format",
                    )
            return normalized
        return normalized

    def accepts_content_type(self, content_type: str | None) -> bool:
        return (
            super().accepts_content_type(content_type)
            or bool(content_type and "csv" in content_type.lower())
        )

    def request_headers(self) -> dict[str, str]:
        return {"Accept": "text/html,application/xhtml+xml,text/csv"}

    def is_csv(self, fetch: FetchResult) -> bool:
        return (
            urllib.parse.urlsplit(fetch.url).path == "/graph/fredgraph.csv"
            or bool(fetch.content_type and "csv" in fetch.content_type.lower())
        )

    def csv_data(self, fetch: FetchResult) -> tuple[list[str], list[list[str]]]:
        try:
            text = self.csv_text(fetch)
            reader = csv.reader(io.StringIO(text))
            headers = next(reader)
            if len(headers) > MAX_CSV_COLUMNS:
                raise WikiAgentError("parse_error", "FRED CSV has too many columns")
            rows: list[list[str]] = []
            for row in reader:
                if len(rows) >= MAX_CSV_ROWS:
                    raise WikiAgentError("parse_error", "FRED CSV has too many rows")
                rows.append(row[:MAX_CSV_COLUMNS])
        except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
            raise WikiAgentError("parse_error", "Unable to parse FRED CSV") from exc
        return headers, rows

    def csv_text(self, fetch: FetchResult) -> str:
        try:
            return fetch.body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise WikiAgentError("parse_error", "Unable to decode FRED CSV") from exc

    def csv_title(self, fetch: FetchResult) -> str:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(fetch.url).query)
        return f"FRED series {values.get('id', ['data'])[0]}"

    def page_type(self, url: str) -> str:
        path = urllib.parse.urlsplit(url).path.casefold()
        if path.startswith("/series/"):
            return "article"
        if path in {"", "/"}:
            return "index"
        return "listing"

    def custom_lead(self, root: etree._Element) -> str | None:
        for paragraph in root.xpath(".//p"):
            text = element_text(paragraph)
            if len(text) >= 80:
                return text
        return None

    def traverse(self, fetch: FetchResult, max_links: int, **options: Any) -> dict[str, Any]:
        if not self.is_csv(fetch):
            return super().traverse(fetch, max_links, **options)
        return {
            "url": fetch.url,
            "title": self.csv_title(fetch),
            "fetched_at": fetch.fetched_at,
            "links": [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "csv",
                    "link_count": 0,
                    "offset": options.get("offset", 0),
                    "next_offset": None,
                    "filters": {
                        "query": options.get("query"),
                        "page_types": options.get("page_types"),
                        "namespaces": options.get("namespaces"),
                    },
                },
            ),
        }

    def skim(
        self,
        fetch: FetchResult,
        *,
        selected_sections: list[str] | None,
        max_links_per_section: int,
    ) -> dict[str, Any]:
        if not self.is_csv(fetch):
            return super().skim(
                fetch,
                selected_sections=selected_sections,
                max_links_per_section=max_links_per_section,
            )
        headers, rows = self.csv_data(fetch)
        include_observations = (
            selected_sections is None or "observations" in selected_sections
        )
        preview = rows[-10:]
        return {
            "url": fetch.url,
            "title": self.csv_title(fetch),
            "fetched_at": fetch.fetched_at,
            "infobox": {"image": None, "fields": []},
            "lead": f"FRED CSV containing {len(rows)} observations.",
            "sections": [
                {
                    "id": "observations",
                    "heading": "Latest observations",
                    "summary": (
                        ", ".join(preview[-1]) if preview else "No observations."
                    ),
                    "link_sentences": [],
                }
            ] if include_observations else [],
            "see_also": [],
            "categories": [],
            "tables": [
                {
                    "section_id": "observations",
                    "caption": "Latest observations",
                    "headers": headers,
                    "rows": preview,
                    "truncated": len(rows) > len(preview),
                }
            ] if include_observations else [],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "csv",
                    "word_count": 0,
                    "total_sections": 1,
                    "sections_truncated": False,
                    "tables_truncated": len(rows) > len(preview),
                    "reliability_hint": "high",
                },
            ),
        }

    def read(self, fetch: FetchResult, *, output_format: str) -> dict[str, Any]:
        if not self.is_csv(fetch):
            return super().read(fetch, output_format=output_format)
        text = self.csv_text(fetch)
        skim = self.skim(
            fetch,
            selected_sections=None,
            max_links_per_section=0,
        )
        return {
            "url": fetch.url,
            "title": self.csv_title(fetch),
            "fetched_at": fetch.fetched_at,
            "text": text,
            "html": None,
            "skim": skim,
            "tables": skim["tables"],
            "meta": self.result_meta(
                fetch,
                {
                    "page_type": "article",
                    "media_type": "csv",
                    "word_count": len(text.split()),
                    "sections_returned": len(skim["sections"]),
                },
            ),
        }
