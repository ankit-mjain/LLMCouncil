"""Tests for structured logging — redaction processor and init_logging."""

from __future__ import annotations

from pathlib import Path

from llmcouncil.logging import _redact_secrets, init_logging


def _run_redact(event_dict: dict) -> dict:
    return _redact_secrets(None, "info", event_dict)


def test_redacts_openai_key() -> None:
    result = _run_redact({"key": "sk-abcdefghijklmnopqrstuvwxyz123456"})
    assert result["key"] == "[REDACTED]"


def test_redacts_anthropic_key() -> None:
    result = _run_redact({"token": "ant-abcdefghijklmnopqrstuvwxyz123456"})
    assert result["token"] == "[REDACTED]"


def test_redacts_telegram_bot_token() -> None:
    result = _run_redact({"t": "bot123456789:ABCDEFghijklmnopqrstuvwxyz0123456789"})
    assert result["t"] == "[REDACTED]"


def test_redacts_tavily_key() -> None:
    result = _run_redact({"key": "tvly-abcdefghijklmnopqrstuvwxyz12345"})
    assert result["key"] == "[REDACTED]"


def test_leaves_normal_strings_intact() -> None:
    result = _run_redact({"message": "council session started", "round": 1})
    assert result["message"] == "council session started"
    assert result["round"] == 1


def test_redacts_secret_embedded_in_message() -> None:
    result = _run_redact({"msg": "token=sk-abcdefghijklmnopqrstuvwxyz123456 used"})
    assert "sk-" not in result["msg"]
    assert "[REDACTED]" in result["msg"]


def test_non_string_values_untouched() -> None:
    result = _run_redact({"count": 42, "flag": True})
    assert result["count"] == 42
    assert result["flag"] is True


def test_init_logging_creates_log_file(tmp_path: Path) -> None:
    init_logging(tmp_path)
    log_file = tmp_path / "llmcouncil.jsonl"
    assert log_file.exists()


def test_init_logging_sets_file_permissions(tmp_path: Path) -> None:
    init_logging(tmp_path)
    log_file = tmp_path / "llmcouncil.jsonl"
    mode = log_file.stat().st_mode & 0o777
    assert mode == 0o640
