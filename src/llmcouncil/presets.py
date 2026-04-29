"""Cost-profile presets from SPECS.md Appendix A."""

from __future__ import annotations

from dataclasses import dataclass, field

from llmcouncil.config import SeatConfig


@dataclass
class PresetDefinition:
    name: str
    description: str
    approx_cost: str
    seats: list[SeatConfig]
    # providers that need API keys for this preset
    required_providers: list[str]
    notes: str = ""


PRESETS: dict[str, PresetDefinition] = {
    "free": PresetDefinition(
        name="free",
        description="All-local Ollama council",
        approx_cost="$0",
        seats=[
            SeatConfig(seat_id=1, role="proposer", provider="ollama", model="qwen2.5:32b"),
            SeatConfig(seat_id=2, role="critic", provider="ollama", model="llama3.3:70b"),
            SeatConfig(seat_id=3, role="judge", provider="ollama", model="deepseek-r1:32b"),
        ],
        required_providers=["ollama"],
        notes="Requires local GPU. Weaker cross-lineage diversity.",
    ),
    "cheap": PresetDefinition(
        name="cheap",
        description="Claude Haiku 4.5 + Kimi K2 + Gemini 2.5 Flash",
        approx_cost="~$0.03/session",
        seats=[
            SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
            SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
            SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
        ],
        required_providers=["anthropic", "moonshot", "google"],
        notes="Recommended starting point — 3 distinct lineages.",
    ),
    "balanced": PresetDefinition(
        name="balanced",
        description="Claude Sonnet 4.6 + GPT-5 + Gemini 2.5 Pro",
        approx_cost="~$0.30/session",
        seats=[
            SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-sonnet-4-6"),
            SeatConfig(seat_id=2, role="critic", provider="openai", model="gpt-5"),
            SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-pro"),
        ],
        required_providers=["anthropic", "openai", "google"],
        notes="Stronger reasoning across all seats.",
    ),
    "premium": PresetDefinition(
        name="premium",
        description="Claude Opus 4.7 + GPT-5 + Gemini 2.5 Pro",
        approx_cost="~$1.00/session",
        seats=[
            SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-opus-4-7"),
            SeatConfig(seat_id=2, role="critic", provider="openai", model="gpt-5"),
            SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-pro"),
        ],
        required_providers=["anthropic", "openai", "google"],
        notes="Frontier seats. Add Kimi K2 as 4th Devil's Advocate seat.",
    ),
    "custom": PresetDefinition(
        name="custom",
        description="Manual configuration",
        approx_cost="varies",
        seats=[],
        required_providers=[],
        notes="Skip preset — configure each seat manually.",
    ),
}

# Known providers with their canonical LiteLLM model IDs
KNOWN_PROVIDERS: dict[str, dict[str, object]] = {
    "anthropic": {
        "label": "Anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7"],
    },
    "openai": {
        "label": "OpenAI",
        "key_env": "OPENAI_API_KEY",
        "models": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini"],
    },
    "google": {
        "label": "Google (Gemini)",
        "key_env": "GEMINI_API_KEY",
        "models": ["gemini/gemini-2.5-flash", "gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash-lite"],
    },
    "xai": {
        "label": "xAI (Grok)",
        "key_env": "XAI_API_KEY",
        "models": ["xai/grok-3", "xai/grok-3-mini"],
    },
    "moonshot": {
        "label": "Moonshot (Kimi)",
        "key_env": "MOONSHOT_API_KEY",
        "models": ["kimi-k2"],
    },
    "groq": {
        "label": "Groq",
        "key_env": "GROQ_API_KEY",
        "models": ["groq/llama-3.3-70b-versatile", "groq/kimi-k2"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"],
    },
    "mistral": {
        "label": "Mistral",
        "key_env": "MISTRAL_API_KEY",
        "models": ["mistral/mistral-small-latest", "mistral/mistral-medium-latest"],
    },
    "together": {
        "label": "Together AI",
        "key_env": "TOGETHER_API_KEY",
        "models": ["together_ai/meta-llama/Llama-3-70b-chat-hf"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "key_env": "OPENROUTER_API_KEY",
        "models": ["openrouter/auto"],
    },
    "ollama": {
        "label": "Ollama (local)",
        "key_env": None,
        "models": ["ollama/llama3.3", "ollama/qwen2.5:32b", "ollama/deepseek-r1:32b"],
    },
}
