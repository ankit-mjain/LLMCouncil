"""Interactive setup wizard — all 16 sections from SPECS.md §7."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich import box

from llmcouncil.adapters.vault import BaseVault, VaultError, build_vault, AgeVault
from llmcouncil.config import (
    AppConfig,
    BudgetConfig,
    CouncilConfig,
    CostProfileConfig,
    DefaultLLMConfig,
    MemoryConfig,
    SeatConfig,
    StreamingConfig,
    TelegramConfig,
    TriggersConfig,
    ValidationConfig,
    VaultConfig,
    VotingConfig,
    WebSearchConfig,
    save_config,
)
from llmcouncil.presets import KNOWN_PROVIDERS, PRESETS

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    console.print()


def _choose(prompt: str, choices: list[str], default: str | None = None) -> str:
    """Display a numbered menu and return the chosen value."""
    for i, choice in enumerate(choices, 1):
        marker = " [dim](default)[/dim]" if choice == default else ""
        console.print(f"  [bold]{i}.[/bold] {choice}{marker}")
    console.print()
    while True:
        raw = Prompt.ask(prompt, default=default or choices[0])
        # accept number or value directly
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        if raw in choices:
            return raw
        console.print(f"[red]Invalid choice '{raw}'. Enter a number 1-{len(choices)} or the value.[/red]")


def _ping_provider(provider: str, model: str, api_key: str | None) -> tuple[bool, str]:
    """1-token connectivity check via LiteLLM."""
    try:
        import litellm  # lazy — avoid slow import at module load

        litellm.suppress_debug_info = True
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        if api_key:
            kwargs["api_key"] = api_key
        litellm.completion(**kwargs)
        return True, "OK"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------------------
# Wizard class
# ---------------------------------------------------------------------------

class SetupWizard:
    def __init__(self, cfg: AppConfig, config_path: Path) -> None:
        self.cfg = cfg.model_copy(deep=True)
        self.config_path = config_path
        self._vault: BaseVault | None = None

    # ------------------------------------------------------------------
    # Section 1 — Welcome & paths
    # ------------------------------------------------------------------

    def _section_welcome(self) -> None:
        _header("1 / 16  —  Welcome & Paths")
        console.print(Panel(
            "[bold]LLMCouncil Setup Wizard[/bold]\n\n"
            "This wizard will configure your multi-LLM council agent.\n"
            "Press [cyan]Enter[/cyan] to accept defaults, or type a new value.",
            title="Welcome",
            border_style="cyan",
        ))
        console.print()

        config_dir = Prompt.ask(
            "Config directory",
            default=str(self.cfg.config_dir),
        )
        self.cfg.config_dir = Path(config_dir).expanduser()

        db_path = Prompt.ask(
            "Database path",
            default=str(self.cfg.db_path),
        )
        self.cfg.db_path = Path(db_path).expanduser()

        logs_dir = Prompt.ask(
            "Logs directory",
            default=str(self.cfg.logs_dir),
        )
        self.cfg.logs_dir = Path(logs_dir).expanduser()

    # ------------------------------------------------------------------
    # Section 2 — Vault
    # ------------------------------------------------------------------

    def _section_vault(self) -> None:
        _header("2 / 16  —  Secrets Vault")
        console.print(
            "Secrets (API keys, bot token) are stored encrypted — never in config.toml.\n"
            "[bold]age[/bold] (default): encrypted file, headless-safe, portable.\n"
            "[bold]keyring[/bold]: OS Secret Service / Keychain — desktop only.\n"
        )

        backend = _choose("Vault backend", ["age", "keyring"], default=self.cfg.vault.backend)

        if backend == "keyring":
            # warn on headless
            if sys.platform == "linux" and not _is_keyring_available():
                console.print(
                    "[yellow]Warning: no keyring daemon detected on this host. "
                    "keyring may fall back to plaintext storage, weakening security.[/yellow]"
                )
                if not Confirm.ask("Continue with keyring anyway?", default=False):
                    backend = "age"

        identity_file = self.cfg.vault.identity_file
        if backend == "age":
            id_path_str = Prompt.ask(
                "Age identity file",
                default=str(self.cfg.vault.identity_file),
            )
            identity_file = Path(id_path_str).expanduser()

            if not identity_file.exists():
                console.print(f"\nGenerating new age identity at [cyan]{identity_file}[/cyan]…")
                pubkey = AgeVault.generate_identity(identity_file)
                console.print(f"[green]Identity generated.[/green] Public key: [bold]{pubkey}[/bold]")
                console.print("[dim]Keep age.key safe — it is the only way to decrypt your secrets.[/dim]\n")
            else:
                console.print(f"[green]Using existing identity:[/green] {identity_file}")

        self.cfg.vault = VaultConfig(backend=backend, identity_file=identity_file)
        self._vault = build_vault(backend, self.cfg.config_dir, identity_file)

    # ------------------------------------------------------------------
    # Section 3 — Cost profile preset
    # ------------------------------------------------------------------

    def _section_cost_profile(self) -> None:
        _header("3 / 16  —  Cost Profile Preset")

        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("Choice", style="bold")
        table.add_column("Preset")
        table.add_column("Council")
        table.add_column("~Cost/session")
        table.add_column("Notes")
        for i, (key, p) in enumerate(PRESETS.items(), 1):
            table.add_row(str(i), key, p.description, p.approx_cost, p.notes)
        console.print(table)

        choices = list(PRESETS.keys())
        preset_name = _choose("Select preset", choices, default=self.cfg.cost_profile.preset)
        self.cfg.cost_profile = CostProfileConfig(preset=preset_name)

        preset = PRESETS[preset_name]
        if preset_name != "custom" and preset.seats:
            console.print(f"\n[green]Preset '{preset_name}' pre-fills council seats.[/green]")
            self._pending_preset_seats = preset.seats[:]
        else:
            self._pending_preset_seats = []

    # ------------------------------------------------------------------
    # Section 4 — Provider registration
    # ------------------------------------------------------------------

    def _section_providers(self) -> None:
        _header("4 / 16  —  Provider Registration")
        console.print(
            "Register each provider you plan to use. API keys are stored in the vault.\n"
            "Select [bold]Done[/bold] when finished.\n"
        )

        # Suggest providers from the chosen preset
        preset = PRESETS[self.cfg.cost_profile.preset]
        suggested = preset.required_providers

        registered = dict(self.cfg.registered_providers)

        provider_list = list(KNOWN_PROVIDERS.keys()) + ["custom", "Done"]

        while True:
            console.print("[bold]Registered so far:[/bold]", ", ".join(registered.keys()) or "(none)")
            if suggested:
                console.print(
                    f"[dim]Suggested for '{self.cfg.cost_profile.preset}' preset: "
                    f"{', '.join(suggested)}[/dim]"
                )
            console.print()

            provider = _choose("Add provider (or Done)", provider_list, default="Done")
            if provider == "Done":
                break

            if provider == "custom":
                provider = Prompt.ask("Custom provider name")

            info = KNOWN_PROVIDERS.get(provider, {})
            key_env: str | None = info.get("key_env")  # type: ignore[assignment]
            default_models: list[str] = list(info.get("models", []))  # type: ignore[arg-type]

            # API key
            if key_env and provider != "ollama":
                api_key = Prompt.ask(
                    f"API key for [bold]{provider}[/bold]",
                    password=True,
                )
                if self._vault:
                    self._vault.set(f"{provider.upper()}_API_KEY", api_key)
                    console.print(f"[green]Key stored in vault.[/green]")
            else:
                api_key = None

            # Model list
            if default_models:
                console.print(f"\nDefault models for {provider}: {', '.join(default_models)}")
                models_str = Prompt.ask(
                    "Models to register (comma-separated, or Enter for defaults)",
                    default=",".join(default_models),
                )
            else:
                models_str = Prompt.ask("Models to register (comma-separated)")
            models = [m.strip() for m in models_str.split(",") if m.strip()]

            # Connectivity ping
            if models and Confirm.ask(f"Test connectivity to {provider}/{models[0]}?", default=True):
                console.print(f"[dim]Pinging {provider}/{models[0]}…[/dim]")
                ok, msg = _ping_provider(provider, models[0], api_key)
                if ok:
                    console.print(f"[green]Connection OK.[/green]")
                else:
                    console.print(f"[yellow]Warning: ping failed: {msg}[/yellow]")
                    if not Confirm.ask("Continue registering this provider anyway?", default=True):
                        continue

            registered[provider] = models
            console.print(f"[green]{provider} registered with {len(models)} model(s).[/green]\n")

        self.cfg.registered_providers = registered

    # ------------------------------------------------------------------
    # Section 5 — Default LLM
    # ------------------------------------------------------------------

    def _section_default_llm(self) -> None:
        _header("5 / 16  —  Default LLM (single-shot mode)")
        console.print("This LLM handles queries that are NOT escalated to the council.\n")

        if not self.cfg.registered_providers:
            console.print("[yellow]No providers registered. Skipping default LLM setup.[/yellow]")
            return

        provider = _choose(
            "Default provider",
            list(self.cfg.registered_providers.keys()),
            default=self.cfg.default_llm.provider or list(self.cfg.registered_providers.keys())[0],
        )
        models = self.cfg.registered_providers[provider]
        model = _choose("Default model", models, default=self.cfg.default_llm.model or models[0])

        # Optional fallback chain
        fallback_chain: list[dict[str, str]] = []
        if Confirm.ask("Add fallback models? (used if primary fails)", default=False):
            while True:
                fb_provider = _choose(
                    "Fallback provider",
                    list(self.cfg.registered_providers.keys()) + ["Done"],
                    default="Done",
                )
                if fb_provider == "Done":
                    break
                fb_models = self.cfg.registered_providers[fb_provider]
                fb_model = _choose("Fallback model", fb_models, default=fb_models[0])
                fallback_chain.append({"provider": fb_provider, "model": fb_model})
                console.print(f"[green]Added fallback: {fb_provider}/{fb_model}[/green]")

        self.cfg.default_llm = DefaultLLMConfig(
            provider=provider,
            model=model,
            fallback_chain=fallback_chain,
        )

    # ------------------------------------------------------------------
    # Section 6 — Council composition
    # ------------------------------------------------------------------

    def _section_council(self) -> None:
        _header("6 / 16  —  Council Composition")

        size = IntPrompt.ask("Council size (≥ 2)", default=self.cfg.council.size)
        if size > 4:
            console.print(
                f"[yellow]Note: {size} seats will increase cost and latency significantly.[/yellow]"
            )

        # Start from preset seats or existing config seats
        seats = list(self._pending_preset_seats or self.cfg.council.seats)

        if seats:
            table = Table(box=box.SIMPLE, header_style="bold cyan", show_header=True)
            table.add_column("Seat")
            table.add_column("Role")
            table.add_column("Provider")
            table.add_column("Model")
            for s in seats:
                table.add_row(str(s.seat_id), s.role, s.provider, s.model)
            console.print("\n[bold]Pre-filled seats from preset:[/bold]")
            console.print(table)
            if not Confirm.ask("Edit seat assignments?", default=False):
                # still need to validate provider count
                pass
            else:
                seats = self._configure_seats(size)
        elif self.cfg.registered_providers:
            seats = self._configure_seats(size)
        else:
            console.print("[yellow]No providers registered — skipping seat configuration.[/yellow]")

        # Devil's Advocate
        devils = Confirm.ask(
            "Enable Devil's Advocate seat? (adds a 4th seat, increases cost)",
            default=self.cfg.council.devils_advocate_enabled,
        )
        if devils and len(seats) < 4:
            console.print("[dim]Configure the Devil's Advocate seat:[/dim]")
            da_seat = self._configure_one_seat(len(seats) + 1, forced_role="devils_advocate")
            seats.append(da_seat)

        # Single-provider check
        providers_used = {s.provider for s in seats}
        min_providers = self.cfg.council.min_distinct_providers
        if len(providers_used) < min_providers:
            console.print(
                f"\n[yellow]Warning: all seats use the same provider lineage. "
                f"Same-lineage members vote near-identically — the council collapses "
                f"toward single-LLM behavior.[/yellow]"
            )
            if Confirm.ask("Allow single-provider council (degraded mode)?", default=False):
                min_providers = 1
            else:
                console.print("[dim]Reconfigure seats to use at least 2 providers.[/dim]")
                seats = self._configure_seats(size)

        self.cfg.council = CouncilConfig(
            size=len(seats),
            rotation=False,
            protocol=self.cfg.council.protocol,
            max_rounds=self.cfg.council.max_rounds,
            include_minority=self.cfg.council.include_minority,
            expose_transcript=self.cfg.council.expose_transcript,
            min_distinct_providers=min_providers,
            devils_advocate_enabled=devils,
            seats=seats,
        )

    def _configure_seats(self, size: int) -> list[SeatConfig]:
        roles_needed = ["proposer"] + ["critic"] * max(1, size - 2) + ["judge"]
        seats: list[SeatConfig] = []
        providers = list(self.cfg.registered_providers.keys())
        if not providers:
            return seats
        for i, role in enumerate(roles_needed[:size], 1):
            console.print(f"\n[bold]Seat {i} — {role}[/bold]")
            seat = self._configure_one_seat(i, forced_role=role)
            seats.append(seat)
        return seats

    def _configure_one_seat(self, seat_id: int, forced_role: str | None = None) -> SeatConfig:
        providers = list(self.cfg.registered_providers.keys())
        provider = _choose(f"  Provider", providers, default=providers[0])
        models = self.cfg.registered_providers[provider]
        model = _choose(f"  Model", models, default=models[0])
        if forced_role:
            role = forced_role
        else:
            role = _choose(
                "  Role",
                ["proposer", "critic", "devils_advocate", "judge"],
                default="critic",
            )
        return SeatConfig(seat_id=seat_id, role=role, provider=provider, model=model)

    # ------------------------------------------------------------------
    # Section 7 — Deliberation protocol
    # ------------------------------------------------------------------

    def _section_protocol(self) -> None:
        _header("7 / 16  —  Deliberation Protocol")

        protocol = _choose(
            "Protocol",
            ["fixed", "freeform"],
            default=self.cfg.council.protocol,
        )
        console.print(
            "\n[dim]fixed:[/dim]  Propose → Critique → Revise → Vote (structured, default)\n"
            "[dim]freeform:[/dim] Critics post freely until they converge or round-cap\n"
        )

        max_rounds = IntPrompt.ask("Max rounds (1–6)", default=self.cfg.council.max_rounds)
        max_rounds = max(1, min(6, max_rounds))
        if max_rounds > 3:
            est_cost = max_rounds * 0.01  # rough estimate
            console.print(
                f"[yellow]Selecting {max_rounds} rounds may take ~{max_rounds * 20}s "
                f"and cost ~${est_cost:.2f} extra per query — proceed?[/yellow]"
            )
            if not Confirm.ask("Proceed with this round count?", default=True):
                max_rounds = 3

        include_minority = Confirm.ask(
            "Include minority opinion in verdict?",
            default=self.cfg.council.include_minority,
        )
        expose_transcript = Confirm.ask(
            "Expose full transcript via /transcript command?",
            default=self.cfg.council.expose_transcript,
        )

        self.cfg.council = self.cfg.council.model_copy(update={
            "protocol": protocol,
            "max_rounds": max_rounds,
            "include_minority": include_minority,
            "expose_transcript": expose_transcript,
        })

    # ------------------------------------------------------------------
    # Section 8 — Voting
    # ------------------------------------------------------------------

    def _section_voting(self) -> None:
        _header("8 / 16  —  Voting")

        mechanism = _choose(
            "Voting mechanism",
            ["simple_majority", "supermajority", "ranked_choice", "weighted", "judge_decides"],
            default=self.cfg.voting.mechanism,
        )
        tie_break = _choose(
            "Tie-breaking",
            ["user", "judge", "re_deliberate"],
            default=self.cfg.voting.tie_break,
        )
        self.cfg.voting = VotingConfig(mechanism=mechanism, tie_break=tie_break)

    # ------------------------------------------------------------------
    # Section 9 — Verdict shape (folded into section 7 above, separate for clarity)
    # ------------------------------------------------------------------

    # Section 10 — Streaming
    # ------------------------------------------------------------------

    def _section_streaming(self) -> None:
        _header("10 / 16  —  Streaming")
        target = _choose(
            "Stream deliberation to",
            ["off", "tui", "telegram", "both"],
            default=self.cfg.streaming.target,
        )
        self.cfg.streaming = StreamingConfig(target=target)

    # ------------------------------------------------------------------
    # Section 11 — Telegram
    # ------------------------------------------------------------------

    def _section_telegram(self) -> None:
        _header("11 / 16  —  Telegram")

        bot_token = Prompt.ask(
            "Telegram bot token (leave blank to skip)",
            default="",
            password=True,
        )
        if bot_token and self._vault:
            self._vault.set("TELEGRAM_BOT_TOKEN", bot_token)
            console.print("[green]Bot token stored in vault.[/green]")

        fmt = _choose(
            "Message format",
            ["plain", "markdown", "rich"],
            default=self.cfg.telegram.message_format,
        )
        console.print(
            "[dim]Authorized chat-id will be set automatically when you send /start to your bot.[/dim]"
        )
        self.cfg.telegram = TelegramConfig(
            authorized_chat_id=self.cfg.telegram.authorized_chat_id,
            message_format=fmt,
        )

    # ------------------------------------------------------------------
    # Section 12 — Budgets
    # ------------------------------------------------------------------

    def _section_budgets(self) -> None:
        _header("12 / 16  —  Cost & Latency Budgets")

        per_session = FloatPrompt.ask(
            "Per-session USD ceiling",
            default=self.cfg.budget.per_session_usd,
        )
        per_query_tokens = IntPrompt.ask(
            "Per-query token cap (cumulative)",
            default=self.cfg.budget.per_query_tokens,
        )
        per_day = FloatPrompt.ask(
            "Per-day USD ceiling",
            default=self.cfg.budget.per_day_usd,
        )
        soft_latency = IntPrompt.ask(
            "Soft latency target (seconds)",
            default=self.cfg.budget.soft_latency_s,
        )
        hard_latency = IntPrompt.ask(
            "Hard latency cancel (seconds)",
            default=self.cfg.budget.hard_latency_s,
        )
        self.cfg.budget = BudgetConfig(
            per_session_usd=per_session,
            per_query_tokens=per_query_tokens,
            per_day_usd=per_day,
            soft_latency_s=soft_latency,
            hard_latency_s=hard_latency,
        )

    # ------------------------------------------------------------------
    # Section 13 — Memory & search
    # ------------------------------------------------------------------

    def _section_memory_search(self) -> None:
        _header("13 / 16  —  Memory & Web Search")

        memory_enabled = Confirm.ask(
            "Enable cross-conversation memory?",
            default=self.cfg.memory.enabled,
        )
        retention = _choose(
            "Memory retention policy",
            ["summarize_after_30d", "keep_forever", "delete_after_30d"],
            default=self.cfg.memory.retention_policy,
        )
        self.cfg.memory = MemoryConfig(
            enabled=memory_enabled,
            retention_policy=retention,
            max_summary_tokens=self.cfg.memory.max_summary_tokens,
        )

        search_enabled = Confirm.ask(
            "Enable web search during deliberation?",
            default=self.cfg.web_search.enabled,
        )
        if search_enabled:
            provider = _choose(
                "Web search provider",
                ["tavily", "serper", "duckduckgo"],
                default=self.cfg.web_search.provider,
            )
            if provider != "duckduckgo":
                search_key = Prompt.ask(
                    f"{provider.capitalize()} API key",
                    password=True,
                    default="",
                )
                if search_key and self._vault:
                    self._vault.set(f"{provider.upper()}_API_KEY", search_key)
                    console.print("[green]Search key stored in vault.[/green]")
            max_calls = IntPrompt.ask(
                "Max web search calls per council session",
                default=self.cfg.web_search.max_calls_per_session,
            )
            self.cfg.web_search = WebSearchConfig(
                provider=provider,
                enabled=True,
                max_calls_per_session=max_calls,
            )
        else:
            self.cfg.web_search = WebSearchConfig(
                provider=self.cfg.web_search.provider,
                enabled=False,
                max_calls_per_session=self.cfg.web_search.max_calls_per_session,
            )

    # ------------------------------------------------------------------
    # Section 14 — Latency (already covered in section 12)
    # Section 15 — Validation logging
    # ------------------------------------------------------------------

    def _section_validation(self) -> None:
        _header("15 / 16  —  Validation Logging")
        console.print(
            "When enabled, every /Council session also runs the same query through the\n"
            "default single-LLM in the background. Results are stored for comparison.\n"
            "You'll be prompted occasionally to pick which answer was better.\n"
            "[dim]May be turned off to halve cost.[/dim]\n"
        )
        ab_logging = Confirm.ask(
            "Enable A/B validation logging?",
            default=self.cfg.validation.ab_logging,
        )
        poll_every = IntPrompt.ask(
            "Prompt for preference every N council sessions",
            default=self.cfg.validation.prompt_user_for_preference_every_n,
        )
        self.cfg.validation = ValidationConfig(
            ab_logging=ab_logging,
            prompt_user_for_preference_every_n=poll_every,
        )

    # ------------------------------------------------------------------
    # Section 16 — Confirmation summary
    # ------------------------------------------------------------------

    def _section_confirm(self) -> None:
        _header("16 / 16  —  Confirmation")

        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Key", style="bold cyan")
        table.add_column("Value")

        table.add_row("Config dir", str(self.cfg.config_dir))
        table.add_row("DB path", str(self.cfg.db_path))
        table.add_row("Vault backend", self.cfg.vault.backend)
        table.add_row("Cost preset", self.cfg.cost_profile.preset)
        table.add_row("Registered providers", ", ".join(self.cfg.registered_providers.keys()) or "(none)")
        table.add_row("Default LLM", f"{self.cfg.default_llm.provider}/{self.cfg.default_llm.model}")
        table.add_row("Council size", str(self.cfg.council.size))
        for s in self.cfg.council.seats:
            table.add_row(f"  Seat {s.seat_id}", f"{s.role} — {s.provider}/{s.model}")
        table.add_row("Protocol", self.cfg.council.protocol)
        table.add_row("Max rounds", str(self.cfg.council.max_rounds))
        table.add_row("Voting", self.cfg.voting.mechanism)
        table.add_row("Tie-break", self.cfg.voting.tie_break)
        table.add_row("Streaming", self.cfg.streaming.target)
        table.add_row("Telegram format", self.cfg.telegram.message_format)
        table.add_row("Budget/session", f"${self.cfg.budget.per_session_usd:.2f}")
        table.add_row("Budget/day", f"${self.cfg.budget.per_day_usd:.2f}")
        table.add_row("Memory", "enabled" if self.cfg.memory.enabled else "disabled")
        table.add_row("Web search", "enabled" if self.cfg.web_search.enabled else "disabled")
        table.add_row("A/B logging", "enabled" if self.cfg.validation.ab_logging else "disabled")

        console.print(table)
        console.print()

        answer = Prompt.ask(
            "Type [bold]confirm[/bold] to save, or [bold]abort[/bold] to discard",
            default="confirm",
        )
        if answer.lower() != "confirm":
            console.print("[yellow]Setup aborted. No changes saved.[/yellow]")
            raise SystemExit(0)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> AppConfig:
        self._pending_preset_seats: list[SeatConfig] = []

        self._section_welcome()
        self._section_vault()
        self._section_cost_profile()
        self._section_providers()
        self._section_default_llm()
        self._section_council()
        self._section_protocol()
        self._section_voting()
        self._section_streaming()
        self._section_telegram()
        self._section_budgets()
        self._section_memory_search()
        self._section_validation()
        self._section_confirm()

        return self.cfg


# ---------------------------------------------------------------------------
# Module-level entry point (called from cli.py)
# ---------------------------------------------------------------------------

def run_wizard(cfg: AppConfig, config_path: Path | None = None) -> AppConfig:
    path = config_path or Path("~/.llmcouncil/config.toml").expanduser()
    return SetupWizard(cfg, path).run()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        import keyring.backend

        backends = keyring.backend.get_all_keyring()
        # filter out the plaintext/null fallback backends
        safe = [b for b in backends if "Fail" not in type(b).__name__ and "null" not in type(b).__name__.lower()]
        return bool(safe)
    except Exception:  # noqa: BLE001
        return False
