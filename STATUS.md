# LLMCouncil — Project Status

> Last updated: 2026-04-29

---

## Current milestone: M6 (not started)

---

## Milestone tracker

| M | Deliverable | Status | Exit criteria |
|---|---|---|---|
| **M0** | Repo scaffold, `pyproject.toml`, CI, config schema, vault adapter | **DONE** | `llmcouncil --help` works; secrets round-trip through age vault |
| **M1** | Single-LLM responder (LiteLLM); basic Telegram bot; cost ledger | **SKIPPED → folded into M3** | Send a message in Telegram, get an answer; cost recorded |
| **M2** | Setup wizard (all 16 sections); cost-profile presets; config.toml round-trip | **DONE** | Wizard produces valid config; reload works; `cheap` preset in < 5 min |
| **M3** | Council orchestrator (fixed protocol, 3 seats, simple majority); transcript persistence; verdict synthesis | **DONE** | `/Council` produces a verdict; transcript stored |
| **M4** | Voting variants, tie-break flows, Devil's Advocate, weighted/ranked | **DONE** | All voting mechanisms covered by tests |
| **M5** | Web search tool; cross-conversation memory; auto-escalation | **DONE** | Memory recall + escalation observable in TUI |
| **M6** | TUI dashboard (live + history) | **TODO** | Live streaming visible during a council session |
| **M7** | Telegram streaming; markdown/rich formats; budget enforcement; failure modes | **TODO** | All §19 failures handled; budgets enforced |
| **M8** | Hardening: structured logs, security review, docs; validation harness active | **TODO** | Security review passed; README; first 30 days of validation data |
| **M9** | v1 → v2 pivot trigger met; begin CSV pipeline spec | **TODO** | v2.0 spec drafted and approved |

---

## M5 — completed 2026-04-29

### What was built

| File | Purpose |
|---|---|
| `src/llmcouncil/tools/web_search.py` | `WebSearchTool` — Tavily adapter; rate-limited (`max_calls_per_session`); `reset_session()`; pluggable provider |
| `src/llmcouncil/memory/store.py` | `MemoryStore` — LLM-written session summaries; cosine-similarity recall via LiteLLM embeddings stored as JSON BLOBs; `write_session_memory()`, `recall()`, `clear()`, `list_summaries()` |
| `src/llmcouncil/persistence/models.py` | `Memory` SQLAlchemy model (`memories` table) — summary_text, embedding_json, topic, entities_json, decisions_json, open_threads_json |
| `src/llmcouncil/agent.py` | `dispatch()` — confidence-based auto-escalation gate; `memory_context` param injected into query; `_parse_confidence()`, `_strip_confidence_footer()` helpers |
| `src/llmcouncil/config.py` | `MemoryConfig.embedding_model` field (default `openai/text-embedding-3-small`) |
| `src/llmcouncil/tui/app.py` | `CouncilTUI.notify()` / `get_notifications()` — escalation + memory recall observable in TUI |
| `tests/unit/test_web_search.py` | 6 tests — disabled, rate-limit, reset, Tavily format, empty results, counter |
| `tests/unit/test_memory.py` | 13 tests — cosine similarity, write/recall/clear/list round-trips |
| `tests/unit/test_agent_escalation.py` | 11 tests — confidence parsing, high-confidence no-escalation, low-confidence escalation, disabled escalation, explicit trigger, memory context injection |

### Test results
```
90 passed in 20.55s
```

---

## M4 — completed 2026-04-29

### What was built

| File | Purpose |
|---|---|
| `src/llmcouncil/config.py` | `SeatConfig.weight: float = 1.0` — per-seat weight for weighted voting |
| `src/llmcouncil/council/voting.py` | `supermajority()`, `ranked_choice()` (instant-runoff), `weighted_vote()`; `VotePayload.rankings` field |
| `src/llmcouncil/council/orchestrator.py` | Devil's Advocate runs in parallel with critics (`kind="dissent"`); `vote_node` skips for `judge_decides`; `synthesize_node` dispatches all mechanisms + tie-break paths; `_judge_decides()` and `_judge_breaks_tie()` helpers; `tie_break` field in `CouncilState` |
| `tests/unit/test_voting.py` | 10 new tests — supermajority, ranked-choice (IRV), weighted, default-weight |
| `tests/unit/test_council_orchestrator.py` | 4 new tests — DA dissent, judge_decides, tie_user_pending, judge tie-break |

### Test results
```
60 passed in 7.22s
```

---

## M3 — completed 2026-04-29

### What was built

| File | Purpose |
|---|---|
| `src/llmcouncil/council/orchestrator.py` | LangGraph `StateGraph` — fixed protocol: Propose → Critique → check termination (unanimity / round-cap) → [Revise]* → Vote → Synthesize |
| `src/llmcouncil/council/llm_adapter.py` | `call_seat()` — async LiteLLM wrapper with latency + cost tracking |
| `src/llmcouncil/council/voting.py` | `simple_majority()` with confidence tie-break; `straw_poll_unanimous()` |
| `src/llmcouncil/council/synthesizer.py` | `render_verdict()` — §11.5 template (Verdict / Council notes / Minority view) |
| `src/llmcouncil/persistence/models.py` | SQLAlchemy models: `sessions`, `seats_snapshot`, `transcript_entries`, `votes`, `verdicts`, `cost_ledger` |
| `src/llmcouncil/persistence/db.py` | `init_db()` — engine + `create_all` + session factory |
| `src/llmcouncil/agent.py` | `single_shot()` (M1), `dispatch()` — routes `/Council` prefix to orchestrator |
| `tests/unit/test_voting.py` | 7 tests — majority, tie-break, straw poll |
| `tests/unit/test_persistence.py` | 5 tests — schema creation, round-trip for all tables |
| `tests/unit/test_council_orchestrator.py` | 7 tests — unanimous early stop, round-cap, vote parse fallback, verdict template |

### Test results
```
47 passed in 8.20s
```

---

## M2 — completed 2026-04-29

### What was built

| File | Purpose |
|---|---|
| `src/llmcouncil/config.py` | Expanded schema — added `CostProfileConfig`, `TriggersConfig`, `ValidationConfig`, `registered_providers`, `expose_transcript`, `soft/hard_latency_s`, `max_calls_per_session`, `logs_dir` |
| `src/llmcouncil/presets.py` | `PRESETS` dict (free/cheap/balanced/premium/custom) + `KNOWN_PROVIDERS` registry with default models per provider |
| `src/llmcouncil/wizard.py` | Full 16-section interactive setup wizard (Typer + Rich); auto-called on first `llmcouncil run` |
| `tests/unit/test_config_extended.py` | 9 tests — full round-trip, all new config fields |
| `tests/unit/test_presets.py` | 5 tests — preset completeness, seat roles, provider diversity |

### Test results
```
28 passed in 0.45s
```

---

## M0 — completed 2026-04-29

### What was built

| File | Purpose |
|---|---|
| `pyproject.toml` | Full dependency spec — LiteLLM, LangGraph, Textual, python-telegram-bot, SQLAlchemy, pyrage, Typer, structlog, pytest, ruff, mypy |
| `src/llmcouncil/config.py` | Pydantic v2 config schema matching locked §8 TOML; `load_config` / `save_config` |
| `src/llmcouncil/adapters/vault.py` | `AgeVault` (age-encrypted JSON, default) + `KeyringVault` (OS keyring, opt-in) + `build_vault` factory |
| `src/llmcouncil/cli.py` | Typer CLI — `setup`, `run`, `tui`, `vault-set`, `vault-get`, `vault-delete` |
| `src/llmcouncil/agent.py` | Agent bootstrap stub (M1) |
| `src/llmcouncil/wizard.py` | Setup wizard stub (M2) |
| `src/llmcouncil/tui/app.py` | TUI dashboard stub (M6) |
| `tests/unit/test_config.py` | 7 tests — config round-trip, seat validation, provider diversity enforcement |
| `tests/unit/test_vault.py` | 8 tests — age encrypt/decrypt, set/get/delete/overwrite, error cases |
| `.github/workflows/ci.yml` | GitHub Actions CI — ruff lint, mypy typecheck, pytest unit tests |
| `.gitignore` | Excludes `.venv`, `*.age`, `age.key`, `*.sqlite`, logs, caches |

### Test results
```
15 passed in 0.16s
```

---

## Open questions

| ID | Question | Status |
|---|---|---|
| OPEN-Q-V4 | Does Council remain as opt-in `/council` mode in v2, or fully retire? | Deferred to v2 design phase |

---

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| LLM abstraction | LiteLLM |
| Orchestration | LangGraph |
| Telegram | python-telegram-bot v21+ |
| TUI | Textual |
| CLI | Typer + Rich |
| Config validation | Pydantic v2 |
| ORM / DB | SQLAlchemy 2.x + SQLite + Alembic |
| Secrets vault | pyrage (age, default) / keyring (opt-in) |
| Web search | Tavily (default) |
| Logging | structlog |
| Packaging | uv + pyproject.toml |
| Tests | pytest + pytest-asyncio + VCR.py |

---

## Spec

Full design spec: `SPECS.md` (v1.0, locked 2026-04-28)
