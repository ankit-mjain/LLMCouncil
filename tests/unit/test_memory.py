"""Memory store unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import DefaultLLMConfig, MemoryConfig
from llmcouncil.memory.store import MemoryStore, _cosine_similarity


def _mem_cfg(**kwargs: object) -> MemoryConfig:
    return MemoryConfig(**kwargs)  # type: ignore[arg-type]


def _llm_cfg() -> DefaultLLMConfig:
    return DefaultLLMConfig(provider="anthropic", model="claude-haiku-4-5")


def _emb_response(vec: list[float]) -> MagicMock:
    m = MagicMock()
    m.data = [{"embedding": vec}]
    return m


def _compl_response(text: str) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = text
    return m


_SUMMARY_JSON = (
    '{"topic":"testing","entities":["pytest"],"decisions":["use mocks"],'
    '"open_threads":[],"summary":"A test session about mocking."}'
)


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical() -> None:
    a = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(a, a) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal() -> None:
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_similarity_zero_vector() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_partial() -> None:
    a = [1.0, 1.0]
    b = [1.0, 0.0]
    score = _cosine_similarity(a, b)
    assert 0.5 < score < 1.0


# ---------------------------------------------------------------------------
# write_session_memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_session_memory_returns_positive_id(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_compl, \
         patch("litellm.aembedding", new_callable=AsyncMock) as mock_emb:
        mock_compl.return_value = _compl_response(_SUMMARY_JSON)
        mock_emb.return_value = _emb_response([1.0, 0.0, 0.0])

        row_id = await store.write_session_memory("sess-1", "Q: hello\nA: world")

    assert row_id > 0


@pytest.mark.asyncio
async def test_write_disabled_returns_minus_one(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(enabled=False), _llm_cfg())
    row_id = await store.write_session_memory(None, "any text")
    assert row_id == -1


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_disabled_returns_empty(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(enabled=False), _llm_cfg())
    results = await store.recall("query")
    assert results == []


@pytest.mark.asyncio
async def test_recall_no_memories_returns_empty(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())
    store._get_session_factory()  # ensure DB initialized

    with patch("litellm.aembedding", new_callable=AsyncMock) as mock_emb:
        mock_emb.return_value = _emb_response([1.0, 0.0])
        results = await store.recall("query")

    # No embedding call needed when table is empty — store short-circuits
    assert results == []


@pytest.mark.asyncio
async def test_recall_returns_most_similar(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())

    def _dogs_json() -> MagicMock:
        return _compl_response(
            '{"topic":"dogs","entities":[],"decisions":[],"open_threads":[],'
            '"summary":"Memory about dogs."}'
        )

    def _cats_json() -> MagicMock:
        return _compl_response(
            '{"topic":"cats","entities":[],"decisions":[],"open_threads":[],'
            '"summary":"Memory about cats."}'
        )

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_compl, \
         patch("litellm.aembedding", new_callable=AsyncMock) as mock_emb:
        mock_compl.side_effect = [_dogs_json(), _cats_json()]
        mock_emb.side_effect = [
            _emb_response([1.0, 0.0, 0.0]),  # write: dogs embedding
            _emb_response([0.0, 1.0, 0.0]),  # write: cats embedding
            _emb_response([0.9, 0.1, 0.0]),  # recall query: close to dogs
        ]
        await store.write_session_memory(None, "session about dogs")
        await store.write_session_memory(None, "session about cats")
        results = await store.recall("dogs", top_k=1)

    assert len(results) == 1
    assert "dogs" in results[0]


# ---------------------------------------------------------------------------
# clear / list_summaries
# ---------------------------------------------------------------------------

def test_clear_empty_store_returns_zero(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())
    store._get_session_factory()
    assert store.clear() == 0


def test_list_summaries_empty(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())
    store._get_session_factory()
    assert store.list_summaries() == []


@pytest.mark.asyncio
async def test_list_summaries_after_write(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_compl, \
         patch("litellm.aembedding", new_callable=AsyncMock) as mock_emb:
        mock_compl.return_value = _compl_response(_SUMMARY_JSON)
        mock_emb.return_value = _emb_response([1.0, 0.0])
        await store.write_session_memory("sess-42", "transcript")

    summaries = store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0]["topic"] == "testing"
    assert summaries[0]["session_id"] == "sess-42"


@pytest.mark.asyncio
async def test_clear_after_write_returns_count(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data.sqlite", _mem_cfg(), _llm_cfg())

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_compl, \
         patch("litellm.aembedding", new_callable=AsyncMock) as mock_emb:
        mock_compl.side_effect = [
            _compl_response(_SUMMARY_JSON),
            _compl_response(_SUMMARY_JSON),
        ]
        mock_emb.return_value = _emb_response([1.0, 0.0])
        await store.write_session_memory(None, "t1")
        await store.write_session_memory(None, "t2")

    count = store.clear()
    assert count == 2
    assert store.list_summaries() == []
