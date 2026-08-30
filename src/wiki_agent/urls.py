from __future__ import annotations


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
