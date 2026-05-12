"""Telegram message formatter — plain / markdown / rich, with 4096-char chunking."""

from __future__ import annotations

import re

_TELEGRAM_MAX = 4096

# Characters that must be escaped in Telegram MarkdownV2.
_MDV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def _escape_mdv2(text: str) -> str:
    return re.sub(r"([" + re.escape(_MDV2_SPECIAL) + r"])", r"\\\1", text)


def _chunk(text: str, max_len: int = _TELEGRAM_MAX) -> list[str]:
    """Split text at logical boundaries (blank lines, then newlines) to fit max_len."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Prefer splitting at a blank line.
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut == -1:
            # Fall back to any newline.
            cut = remaining.rfind("\n", 0, max_len)
        if cut == -1:
            # Hard cut at max_len.
            cut = max_len
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def format_plain(text: str, max_len: int = _TELEGRAM_MAX) -> list[str]:
    return _chunk(text, max_len)


def format_markdown(text: str, max_len: int = _TELEGRAM_MAX) -> list[str]:
    """Escape for Telegram MarkdownV2 and chunk."""
    # Preserve existing **bold** and _italic_ patterns before escaping other chars.
    # Strategy: escape everything, then restore intentional bold/italic markers.
    escaped = _escape_mdv2(text)
    # Restore **bold** → *bold* (MarkdownV2 uses single * for bold)
    escaped = re.sub(r"\\\*\\\*(.+?)\\\*\\\*", r"*\1*", escaped)
    # Restore _italic_
    escaped = re.sub(r"\\_(.+?)\\_", r"_\1_", escaped)
    return _chunk(escaped, max_len)


def format_rich(text: str, max_len: int = _TELEGRAM_MAX) -> list[str]:
    """Add structural emphasis then apply MarkdownV2 escaping."""
    # Bold section headers (lines ending in ":" or matching "[Section]" pattern).
    lines = text.splitlines()
    enriched_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\[.+\]$", stripped) or (stripped.endswith(":") and len(stripped) < 60):
            enriched_lines.append(f"**{stripped}**")
        else:
            enriched_lines.append(line)
    enriched = "\n".join(enriched_lines)
    return format_markdown(enriched, max_len)


def format_message(
    text: str,
    fmt: str = "plain",
    max_len: int = _TELEGRAM_MAX,
) -> list[str]:
    """Return a list of message chunks ready to send via Telegram."""
    if fmt == "markdown":
        return format_markdown(text, max_len)
    if fmt == "rich":
        return format_rich(text, max_len)
    return format_plain(text, max_len)
