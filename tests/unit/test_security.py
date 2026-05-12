"""Security hardening tests — DB permissions, web search injection guard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, WebSearchConfig
from llmcouncil.persistence.db import init_db
from llmcouncil.tools.web_search import WebSearchTool, _INJECTION_GUARD


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
