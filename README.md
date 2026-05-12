# LLMCouncil

A multi-LLM council agent that convenes a panel of AI models to debate a question and produce a synthesised verdict. Ships as a Telegram bot with an optional Textual TUI dashboard.

---

## Architecture

```
User (Telegram / TUI)
        │
        ▼
   agent.dispatch()
        │
        ├── single-shot (default)  ──► LiteLLM → answer
        │
        └── /Council trigger ──────► LangGraph orchestrator
                                         │
                              ┌──────────┴──────────┐
                           Propose              Critique
                           (seat 1)          (seats 2…N)
                              │                    │
                           Revise ◄────────────────┘
                              │
                            Vote → Synthesise → Verdict
                              │
                         EventBus → TUI / Telegram streaming
```

All LLM calls go through LiteLLM, so any provider (Anthropic, OpenAI, Google, Moonshot, DeepSeek, …) works as a seat.

---

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- API keys for at least two distinct LLM providers
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Optional: Tavily API key for web search

---

## Install

```bash
git clone https://github.com/ankitjain/LLMCouncil
cd LLMCouncil
uv sync
```

---

## First run

```bash
uv run llmcouncil setup
```

The interactive wizard walks through all 16 config sections and saves `~/.llmcouncil/config.toml`. Secrets (API keys, bot token) are stored in an age-encrypted vault at `~/.llmcouncil/vault.age`.

To reconfigure later:

```bash
uv run llmcouncil setup --reconfigure
```

---

## Run

```bash
uv run llmcouncil run
```

Starts the Telegram bot in long-poll mode. On first `/start` from a Telegram client the bot pairs with that chat — all subsequent chats are refused.

### Optional: TUI dashboard

```bash
uv run llmcouncil tui
```

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Pair this chat with the bot |
| `/help` | Show available commands |
| `/Council <query>` | Convene the council (3 seats, up to 3 rounds) |
| `/cost` | Show session cost |
| `/budget` | Show per-session and per-day budget limits |
| `/memory show` | Recall recent session summaries |
| `/memory clear` | Clear session-level memory |
| `/transcript <id>` | Retrieve a session transcript |
| `/cancel` | Cancel the active council session |
| `/validation` | Show §26 validation dashboard |
| `/prefer council\|single\|tie\|skip` | Record your preference after a poll |

---

## TUI key bindings

| Key | Action |
|---|---|
| `q` | Quit |
| `c` | Show session cost |
| `m` | Memory summary |
| `s` | Pause session |
| `v` | Validation dashboard |

---

## Vault management

```bash
# Store a secret
uv run llmcouncil vault-set ANTHROPIC_API_KEY sk-ant-...

# Retrieve a secret
uv run llmcouncil vault-get ANTHROPIC_API_KEY

# Delete a secret
uv run llmcouncil vault-delete ANTHROPIC_API_KEY
```

---

## Config

Config lives at `~/.llmcouncil/config.toml`. Key sections:

```toml
[council]
max_rounds = 3
min_distinct_providers = 2

[[council.seats]]
seat_id = 1
role = "proposer"
provider = "anthropic"
model = "claude-haiku-4-5"

[[council.seats]]
seat_id = 2
role = "critic"
provider = "google"
model = "gemini/gemini-2.5-flash"

[[council.seats]]
seat_id = 3
role = "judge"
provider = "openai"
model = "gpt-4o-mini"

[budget]
per_session_usd = 0.50
per_day_usd = 5.00
hard_latency_s = 90

[validation]
ab_logging = true
prompt_user_for_preference_every_n = 5
```

---

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src tests

# Type check
uv run mypy src
```

---

## Security

- Bot refuses all messages from unpaired chats before any processing.
- Setup wizard is local-only — not accessible via Telegram.
- Secrets stored in age-encrypted vault; never written to config.toml.
- DB file created mode `0600`; log file mode `0640`; vault and age key `0600`.
- Web search results are tagged as untrusted before being passed to seats.
- Logs redact API keys and bot tokens via a structlog processor.
