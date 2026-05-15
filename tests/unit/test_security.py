"""Security hardening tests — DB permissions, web search injection guard, secret redaction."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, WebSearchConfig
from llmcouncil.persistence.db import init_db
from llmcouncil.tools.web_search import WebSearchTool, _INJECTION_GUARD
from llmcouncil.wizard import _ping_provider


# ---------------------------------------------------------------------------
# DB file permissions
# ---------------------------------------------------------------------------

def test_init_db_creates_file_mode_600(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    assert db_path.exists()
    mode = db_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_init_db_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    init_db(db_path)  # second call must not raise
    assert db_path.exists()


# ---------------------------------------------------------------------------
# Web search injection guard
# ---------------------------------------------------------------------------

def _make_tool(enabled: bool = True) -> WebSearchTool:
    cfg = WebSearchConfig(enabled=enabled, provider="tavily", max_calls_per_session=10)
    return WebSearchTool(cfg=cfg, api_key="tvly-fake")


@pytest.mark.asyncio
async def test_search_result_has_injection_guard() -> None:
    tool = _make_tool()
    fake_results = {
        "results": [{"title": "T", "url": "http://x.com", "content": "body text"}]
    }
    with patch.object(tool, "_tavily_search", new=AsyncMock(return_value="body text")):
        result = await tool.search("what is 2+2")
    assert result.startswith(_INJECTION_GUARD)
    assert "body text" in result


@pytest.mark.asyncio
async def test_empty_search_result_has_no_guard() -> None:
    tool = _make_tool()
    with patch.object(tool, "_tavily_search", new=AsyncMock(return_value="")):
        result = await tool.search("query")
    assert result == ""


@pytest.mark.asyncio
async def test_disabled_search_returns_empty() -> None:
    tool = _make_tool(enabled=False)
    result = await tool.search("anything")
    assert result == ""


# ---------------------------------------------------------------------------
# Wizard: API key redaction in exception messages (HIGH-003)
# ---------------------------------------------------------------------------

def test_ping_provider_redacts_api_key_in_error() -> None:
    """_ping_provider must not expose API key tokens in the returned error string."""
    import litellm

    fake_exc = Exception("AuthenticationError: Invalid key sk-ant-abc1234567890ABCDEFGH for model")
    with patch("litellm.completion", side_effect=fake_exc):
        ok, msg = _ping_provider("anthropic", "claude-haiku-4-5", "sk-ant-abc1234567890ABCDEFGH")

    assert not ok
    assert "sk-ant-" not in msg
    assert "[REDACTED]" in msg


def test_ping_provider_redacts_openai_key_in_error() -> None:
    fake_exc = Exception("Incorrect API key sk-abcDEFghijKLMNopqrSTUVwxyz provided.")
    with patch("litellm.completion", side_effect=fake_exc):
        ok, msg = _ping_provider("openai", "gpt-4o", "sk-abcDEFghijKLMNopqrSTUVwxyz")

    assert not ok
    assert "sk-" not in msg
    assert "[REDACTED]" in msg


def test_ping_provider_normal_error_not_redacted() -> None:
    fake_exc = Exception("Connection timed out after 30s")
    with patch("litellm.completion", side_effect=fake_exc):
        ok, msg = _ping_provider("anthropic", "claude-haiku-4-5", None)

    assert not ok
    assert "timed out" in msg


# ---------------------------------------------------------------------------
# DB chmod failure is logged, not silently swallowed (MED-002)
# ---------------------------------------------------------------------------

def test_init_db_logs_chmod_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db_path = tmp_path / "test.sqlite"
    with patch("os.chmod", side_effect=OSError("read-only filesystem")):
        with caplog.at_level("WARNING", logger="llmcouncil.persistence.db"):
            init_db(db_path)
    assert any("Failed to set database file permissions" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Log chmod failure is written to stderr, not silently swallowed (MED-001)
# ---------------------------------------------------------------------------

def test_init_logging_warns_on_chmod_failure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from llmcouncil.logging import init_logging

    with patch("os.chmod", side_effect=OSError("read-only filesystem")):
        init_logging(tmp_path)

    captured = capsys.readouterr()
    assert "Failed to set log file permissions" in captured.err


# ---------------------------------------------------------------------------
# Config: model/provider name validation (MED-005)
# ---------------------------------------------------------------------------

def test_seat_config_rejects_shell_injection_in_model() -> None:
    from pydantic import ValidationError
    from llmcouncil.config import SeatConfig

    with pytest.raises(ValidationError, match="Invalid characters"):
        SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude; rm -rf /")


def test_seat_config_rejects_injection_in_provider() -> None:
    from pydantic import ValidationError
    from llmcouncil.config import SeatConfig

    with pytest.raises(ValidationError, match="Invalid characters"):
        SeatConfig(seat_id=1, role="proposer", provider="bad provider!", model="gpt-4o")


def test_seat_config_accepts_valid_names() -> None:
    from llmcouncil.config import SeatConfig

    seat = SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-opus-4-7")
    assert seat.model == "claude-opus-4-7"
    seat2 = SeatConfig(seat_id=2, role="critic", provider="openai", model="gpt-4o-mini")
    assert seat2.provider == "openai"
