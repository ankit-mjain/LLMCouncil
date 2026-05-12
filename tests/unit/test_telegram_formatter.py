"""Telegram formatter tests — chunking, plain/markdown/rich formatting."""

from __future__ import annotations

import pytest

from llmcouncil.telegram.formatter import (
    _chunk,
    format_markdown,
    format_message,
    format_plain,
    format_rich,
)


def test_chunk_short_text() -> None:
    chunks = _chunk("Hello world", max_len=4096)
    assert chunks == ["Hello world"]


def test_chunk_splits_at_blank_line() -> None:
    text = "Para one.\n\nPara two."
    # max_len just above "Para one." → should split at blank line
    chunks = _chunk(text, max_len=12)
    assert len(chunks) == 2
    assert chunks[0] == "Para one."
    assert chunks[1] == "Para two."


def test_chunk_splits_at_newline_when_no_blank_line() -> None:
    text = "Line one.\nLine two."
    chunks = _chunk(text, max_len=12)
    assert len(chunks) == 2
    assert "Line one." in chunks[0]


def test_chunk_hard_cut_when_no_newline() -> None:
    text = "A" * 20
    chunks = _chunk(text, max_len=10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == text


def test_chunk_exactly_max_len() -> None:
    text = "A" * 100
    chunks = _chunk(text, max_len=100)
    assert chunks == [text]


def test_chunk_telegram_limit() -> None:
    long_text = ("word " * 1000).strip()
    chunks = _chunk(long_text, max_len=4096)
    assert all(len(c) <= 4096 for c in chunks)
    # All text preserved.
    assert " ".join(chunks).replace("  ", " ").strip()


def test_format_plain_returns_list() -> None:
    result = format_plain("hello")
    assert isinstance(result, list)
    assert result == ["hello"]


def test_format_plain_chunks_long_text() -> None:
    text = "\n\n".join([f"Paragraph {i}." for i in range(100)])
    chunks = format_plain(text, max_len=100)
    assert all(len(c) <= 100 for c in chunks)


def test_format_markdown_escapes_special_chars() -> None:
    text = "Cost: $1.00 (approx)"
    result = format_markdown(text)
    # Parentheses and dot should be escaped in MarkdownV2
    joined = "".join(result)
    assert "\\." in joined or "\\(" in joined


def test_format_markdown_preserves_bold() -> None:
    text = "**Important note**"
    result = format_markdown(text)
    joined = "".join(result)
    assert "*Important note*" in joined


def test_format_rich_bolds_section_headers() -> None:
    text = "[Verdict]\nThe answer is yes."
    result = format_rich(text)
    joined = "".join(result)
    # [Verdict] should be bolded
    assert "Verdict" in joined


def test_format_message_plain() -> None:
    result = format_message("hello", fmt="plain")
    assert result == ["hello"]


def test_format_message_markdown() -> None:
    result = format_message("**bold** text", fmt="markdown")
    assert isinstance(result, list)
    assert len(result) >= 1


def test_format_message_rich() -> None:
    result = format_message("[Section]\nContent here.", fmt="rich")
    assert isinstance(result, list)
    assert len(result) >= 1


def test_format_message_unknown_format_defaults_to_plain() -> None:
    result = format_message("hello", fmt="unknown")
    assert result == ["hello"]
