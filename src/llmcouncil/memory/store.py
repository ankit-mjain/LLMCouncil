"""Cross-conversation memory store — write summaries, recall by cosine similarity."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
import structlog

from llmcouncil.config import DefaultLLMConfig, MemoryConfig

log = structlog.get_logger(__name__)

_SUMMARY_PROMPT = """\
You are a Memory Writer. Summarize this conversation session in ≤ 300 tokens.
Respond ONLY with JSON (no markdown) in this exact schema:
{"topic": "<short label>", "entities": ["..."], "decisions": ["..."], "open_threads": ["..."], "summary": "<≤300 token summary>"}
"""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


class MemoryStore:
    def __init__(
        self,
        db_path: Path,
        cfg: MemoryConfig,
        default_llm: DefaultLLMConfig,
    ) -> None:
        self._db_path = db_path
        self._cfg = cfg
        self._llm = default_llm
        self._session_factory = None

    def _get_session_factory(self):  # type: ignore[return]
        if self._session_factory is None:
            from llmcouncil.persistence.db import init_db
            self._session_factory = init_db(self._db_path)
        return self._session_factory

    async def _embed(self, text: str) -> list[float]:
        response = await litellm.aembedding(  # type: ignore[attr-defined]
            model=self._cfg.embedding_model,
            input=[text],
        )
        return response.data[0]["embedding"]

    async def _summarize(self, transcript_text: str) -> dict[str, Any]:
        model_str = (
            self._llm.model
            if "/" in self._llm.model
            else f"{self._llm.provider}/{self._llm.model}"
        )
        response = await litellm.acompletion(  # type: ignore[attr-defined]
            model=model_str,
            messages=[
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": f"Session transcript:\n{transcript_text}"},
            ],
            max_tokens=400,
        )
        text: str = response.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {
            "topic": "unknown",
            "entities": [],
            "decisions": [],
            "open_threads": [],
            "summary": text[:300],
        }

    async def write_session_memory(
        self, session_id: str | None, transcript_text: str
    ) -> int:
        """Summarize a session and persist the memory. Returns the new row id, or -1 if disabled."""
        if not self._cfg.enabled:
            return -1

        summary_data = await self._summarize(transcript_text)
        summary_text = summary_data.get("summary", transcript_text[:300])
        embedding = await self._embed(summary_text)

        from llmcouncil.persistence.models import Memory

        now = datetime.now(timezone.utc)
        row = Memory(
            session_id=session_id,
            summary_text=summary_text,
            embedding_json=json.dumps(embedding),
            topic=summary_data.get("topic"),
            entities_json=json.dumps(summary_data.get("entities", [])),
            decisions_json=json.dumps(summary_data.get("decisions", [])),
            open_threads_json=json.dumps(summary_data.get("open_threads", [])),
            created_at=now,
            expires_at=None,
        )
        factory = self._get_session_factory()
        with factory() as db_session:
            db_session.add(row)
            db_session.commit()
            db_session.refresh(row)
            row_id = int(row.id)
        log.info("memory_written", row_id=row_id, topic=summary_data.get("topic"))
        return row_id

    async def recall(self, query: str, top_k: int = 5) -> list[str]:
        """Return top-K memory summaries most relevant to the query."""
        if not self._cfg.enabled:
            return []

        from llmcouncil.persistence.models import Memory

        factory = self._get_session_factory()
        with factory() as db_session:
            rows = db_session.query(Memory).all()

        if not rows:
            return []

        query_embedding = await self._embed(query)
        scored: list[tuple[float, str]] = []
        for row in rows:
            if row.embedding_json:
                try:
                    emb: list[float] = json.loads(row.embedding_json)
                    score = _cosine_similarity(query_embedding, emb)
                    scored.append((score, row.summary_text))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in scored[:top_k]]

    def clear(self) -> int:
        """Wipe all memories. Returns number of rows deleted."""
        from llmcouncil.persistence.models import Memory

        factory = self._get_session_factory()
        with factory() as db_session:
            count: int = db_session.query(Memory).count()
            db_session.query(Memory).delete()
            db_session.commit()
        return count

    def list_summaries(self) -> list[dict[str, Any]]:
        """Return all memory summaries as lightweight dicts (most recent first)."""
        from llmcouncil.persistence.models import Memory

        factory = self._get_session_factory()
        with factory() as db_session:
            rows = db_session.query(Memory).order_by(Memory.created_at.desc()).all()
        return [
            {
                "id": row.id,
                "session_id": row.session_id,
                "topic": row.topic,
                "summary": row.summary_text,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
