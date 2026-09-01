from __future__ import annotations

import json
import urllib.parse
from typing import Any

from lxml import etree, html

from ..errors import WikiAgentError
from .generic import GenericHtmlAdapter, clean_text, element_text


class RetailHtmlAdapter(GenericHtmlAdapter):
    canonical_host: str

    def validate_url(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise WikiAgentError("invalid_request", "url must be a non-empty string")
        parsed = urllib.parse.urlsplit(value)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if parsed.scheme != "https" or hostname not in self.hosts:
            raise WikiAgentError(
                "invalid_request",
                f"url is not supported by the {self.name} adapter",
            )
        if parsed.username or parsed.password or parsed.port:
            raise WikiAgentError(
                "invalid_request",
                "url must not contain credentials or a port",
            )
        if parsed.query:
            raise WikiAgentError(
                "invalid_request",
                f"query URLs are blocked by the {self.name} adapter",
            )
        normalized = urllib.parse.urlunsplit(
            (parsed.scheme, self.canonical_host, parsed.path, "", "")
        )
        return super().validate_url(normalized)

    def robots_url(self, url: str) -> str:
        return f"https://{self.canonical_host}/robots.txt"

    def request_headers(self) -> dict[str, str]:
        return {"Accept-Language": "en-US,en;q=0.9"}

    def discovery_link(self, value: str | None, base_url: str) -> str | None:
        return self.normalize_link(value, base_url)

    def normalize_link(self, value: str | None, base_url: str) -> str | None:
        if not value or value.startswith(("javascript:", "mailto:", "tel:")):
            return None
        absolute = urllib.parse.urljoin(base_url, value)
        parsed = urllib.parse.urlsplit(absolute)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if hostname not in self.hosts:
            return None
        without_query = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        try:
            return self.validate_url(without_query)
        except WikiAgentError:
            return None

    def title(self, document: html.HtmlElement, root: etree._Element) -> str:
        for xpath in (
            "//meta[@property='og:title']/@content",
            "//meta[@name='twitter:title']/@content",
        ):
            values = document.xpath(xpath)
            if values and (title := clean_text(values[0])):
                return title
        return super().title(document, root)

    def custom_lead(self, root: etree._Element) -> str | None:
        for paragraph in root.xpath(".//p"):
            text = element_text(paragraph)
            if len(text) >= 60:
                return text
        return None

    def metadata(
        self,
        document: html.HtmlElement,
        root: etree._Element,
    ) -> dict[str, Any]:
        for script in document.xpath("//script[@type='application/ld+json']"):
            try:
                payload = json.loads(script.text or "")
            except json.JSONDecodeError:
                continue
            for item in self._json_objects(payload):
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if "Product" not in types:
                    continue
                fields: list[dict[str, str]] = []
                brand = item.get("brand")
                if isinstance(brand, dict):
                    brand = brand.get("name")
                self._append_field(fields, "Brand", brand)
                self._append_field(fields, "SKU", item.get("sku"))
                self._append_field(fields, "Model", item.get("model"))
                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict):
                    self._append_field(fields, "Price", offers.get("price"))
                    self._append_field(
                        fields,
                        "Currency",
                        offers.get("priceCurrency"),
                    )
                    availability = offers.get("availability")
                    if isinstance(availability, str):
                        availability = availability.rsplit("/", 1)[-1]
                    self._append_field(fields, "Availability", availability)
                image = item.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                if isinstance(image, dict):
                    image = image.get("url")
                return {
                    "image": image if isinstance(image, str) else None,
                    "fields": fields,
                }
        return {"image": None, "fields": []}

    def _json_objects(self, value: object) -> list[dict[str, Any]]:
        pending = [value]
        objects: list[dict[str, Any]] = []
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                objects.append(item)
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return objects

    def _append_field(
        self,
        fields: list[dict[str, str]],
        key: str,
        value: object,
    ) -> None:
        if isinstance(value, (str, int, float)) and str(value).strip():
            fields.append({"key": key, "value": str(value).strip()})
