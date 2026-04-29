# LLMCouncil — Project Status

> Last updated: 2026-04-29

---

## Current milestone: M3 (not started)

---

## Milestone tracker

| M | Deliverable | Status | Exit criteria |
|---|---|---|---|
| **M0** | Repo scaffold, `pyproject.toml`, CI, config schema, vault adapter | **DONE** | `llmcouncil --help` works; secrets round-trip through age vault |
| **M1** | Single-LLM responder (LiteLLM); basic Telegram bot; cost ledger | **SKIPPED → folded into M3** | Send a message in Telegram, get an answer; cost recorded |
| **M2** | Setup wizard (all 16 sections); cost-profile presets; config.toml round-trip | **DONE** | Wizard produces valid config; reload works; `cheap` preset in < 5 min |
| **M3** | Council orchestrator (fixed protocol, 3 seats, simple majority); transcript persistence; verdict synthesis | **TODO** | `/Council` produces a verdict; transcript stored |
| **M4** | Voting variants, tie-break flows, Devil's Advocate, weighted/ranked | **TODO** | All voting mechanisms covered by tests |
| **M5** | Web search tool; cross-conversation memory; auto-escalation | **TODO** | Memory recall + escalation observable in TUI |
| **M6** | TUI dashboard (live + history) | **TODO** | Live streaming visible during a council session |
| **M7** | Telegram streaming; markdown/rich formats; budget enforcement; failure modes | **TODO** | All §19 failures handled; budgets enforced |
| **M8** | Hardening: structured logs, security review, docs; validation harness active | **TODO** | Security review passed; README; first 30 days of validation data |
| **M9** | v1 → v2 pivot trigger met; begin CSV pipeline spec | **TODO** | v2.0 spec drafted and approved |

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
