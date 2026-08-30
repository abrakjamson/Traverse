from __future__ import annotations

import ipaddress
import urllib.parse


ALLOWED_NAMESPACES = {"main", "category", "portal", "wikipedia"}
KNOWN_NAMESPACES = {
    "book",
    "book_talk",
    "category",
    "category_talk",
    "draft",
    "draft_talk",
    "education_program",
    "education_program_talk",
    "file",
    "file_talk",
    "gadget",
    "gadget_definition",
    "gadget_definition_talk",
    "gadget_talk",
    "help",
    "help_talk",
    "image",
    "image_talk",
    "media",
    "mediawiki",
    "mediawiki_talk",
    "module",
    "module_talk",
    "portal",
    "portal_talk",
    "project",
    "project_talk",
    "special",
    "talk",
    "template",
    "template_talk",
    "timedtext",
    "timedtext_talk",
    "topic",
    "user",
    "user_talk",
    "wikipedia",
    "wikipedia_talk",
}
BLOCKED_NAMESPACES = KNOWN_NAMESPACES - ALLOWED_NAMESPACES


def namespace_for_title(title: str) -> str:
    if ":" not in title:
        return "main"
    candidate = title.split(":", 1)[0].lower().replace(" ", "_")
    return candidate if candidate in KNOWN_NAMESPACES else "main"


def normalize_external_https_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, value))
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port is not None
    ):
        return None
    normalized_host = hostname.rstrip(".").lower()
    if (
        normalized_host == "localhost"
        or normalized_host.endswith((".localhost", ".local", ".internal"))
        or normalized_host == "0.0.0.0"
    ):
        return None
    if "%" in normalized_host:
        return None
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    if address is not None:
        netloc = f"[{address.compressed}]" if address.version == 6 else address.compressed
    else:
        try:
            netloc = normalized_host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    decoded_path = urllib.parse.unquote(parsed.path or "/")
    if any(segment == ".." for segment in decoded_path.split("/")):
        return None
    path = urllib.parse.quote(decoded_path, safe="/:@()_,-.~!$&'()*+;=")
    if any(ord(character) < 32 for character in parsed.query):
        return None
    query = urllib.parse.quote(
        parsed.query,
        safe="!$&'()*+,-./:;=?@_~%",
    )
    return urllib.parse.urlunsplit(("https", netloc, path, query, ""))
