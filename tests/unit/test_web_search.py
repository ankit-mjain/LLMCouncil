"""Web search tool unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import WebSearchConfig
from llmcouncil.tools.web_search import WebSearchTool


def _cfg(**kwargs: object) -> WebSearchConfig:
    return WebSearchConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_disabled_returns_empty() -> None:
    tool = WebSearchTool(_cfg(enabled=False), api_key="dummy")
    result = await tool.search("query")
    assert result == ""
    assert tool.calls_this_session == 0


@pytest.mark.asyncio
async def test_search_rate_limited() -> None:
    tool = WebSearchTool(_cfg(max_calls_per_session=2), api_key="dummy")

    with patch.object(tool, "_tavily_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = "result"
        await tool.search("q1")
        await tool.search("q2")
        result = await tool.search("q3")  # third call — rate-limited

    assert tool.calls_this_session == 2
    assert mock_search.call_count == 2
    assert result == ""


@pytest.mark.asyncio
async def test_search_reset_session() -> None:
    tool = WebSearchTool(_cfg(max_calls_per_session=1), api_key="dummy")

    with patch.object(tool, "_tavily_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = "result"
        await tool.search("q1")
        assert tool.calls_this_session == 1

        tool.reset_session()
        assert tool.calls_this_session == 0

        await tool.search("q2")
        assert tool.calls_this_session == 1


@pytest.mark.asyncio
async def test_tavily_formats_results() -> None:
    tool = WebSearchTool(_cfg(), api_key="test_key")
    mock_response = {
        "results": [
            {"title": "Foo", "url": "https://foo.com", "content": "Foo content"},
            {"title": "Bar", "url": "https://bar.com", "content": "Bar content"},
        ]
    }
    mock_client = AsyncMock()
    mock_client.search.return_value = mock_response

    with patch("llmcouncil.tools.web_search.AsyncTavilyClient", return_value=mock_client):
        result = await tool.search("test query")

    assert "[Foo](https://foo.com)" in result
    assert "Foo content" in result
    assert "[Bar](https://bar.com)" in result
    assert tool.calls_this_session == 1


@pytest.mark.asyncio
async def test_tavily_empty_results_returns_empty() -> None:
    tool = WebSearchTool(_cfg(), api_key="test_key")
    mock_client = AsyncMock()
    mock_client.search.return_value = {"results": []}

    with patch("llmcouncil.tools.web_search.AsyncTavilyClient", return_value=mock_client):
        result = await tool.search("query")

    assert result == ""


@pytest.mark.asyncio
async def test_search_increments_counter() -> None:
    tool = WebSearchTool(_cfg(max_calls_per_session=5), api_key="dummy")

    with patch.object(tool, "_tavily_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = "r"
        for _ in range(3):
            await tool.search("q")

    assert tool.calls_this_session == 3
