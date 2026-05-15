"""Main CLI entry point — `llmcouncil` command."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from llmcouncil.config import AppConfig, load_config, save_config

app = typer.Typer(
    name="llmcouncil",
    help="Multi-LLM Council Agent — Telegram + TUI interfaces.",
    add_completion=False,
)
console = Console()

_DEFAULT_CONFIG_DIR = Path("~/.llmcouncil").expanduser()
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.toml"


def _load_or_default(config_path: Path) -> AppConfig:
    if config_path.exists():
        return load_config(config_path)
    return AppConfig()


@app.command()
def setup(
    reconfigure: bool = typer.Option(False, "--reconfigure", "-r", help="Re-run wizard over existing config."),
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c", help="Config file path."),
) -> None:
    """Run the interactive setup wizard."""
    from llmcouncil.wizard import run_wizard

    cfg = _load_or_default(config) if reconfigure else AppConfig()
    updated = run_wizard(cfg, config_path=config)
    save_config(updated, config)
    console.print(f"\n[green]Config saved to {config}[/green]")


@app.command()
def run(
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c", help="Config file path."),
) -> None:
    """Start the agent (Telegram + optional TUI)."""
    if not config.exists():
        console.print("[yellow]No config found. Starting setup wizard…[/yellow]\n")
        from llmcouncil.wizard import run_wizard

        cfg = run_wizard(AppConfig(), config_path=config)
        save_config(cfg, config)
        console.print(f"[green]Config saved to {config}[/green]\n")
    cfg = load_config(config)
    from llmcouncil.agent import start_agent

    import asyncio

    asyncio.run(start_agent(cfg))


@app.command()
def tui(
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c", help="Config file path."),
) -> None:
    """Launch the TUI dashboard."""
    if not config.exists():
        console.print("[red]No config found. Run `llmcouncil setup` first.[/red]")
        raise typer.Exit(1)
    cfg = load_config(config)
    from llmcouncil.tui.app import CouncilTUI

    CouncilTUI(cfg).run()


@app.command("vault-set")
def vault_set(
    key: str = typer.Argument(..., help="Secret key name (e.g. ANTHROPIC_API_KEY)."),
    value: str = typer.Argument(..., help="Secret value."),
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c"),
) -> None:
    """Store a secret in the vault."""
    cfg = _load_or_default(config)
    from llmcouncil.adapters.vault import build_vault

    vault = build_vault(cfg.vault.backend, cfg.config_dir, cfg.vault.identity_file)
    vault.set(key, value)
    console.print(f"[green]Secret '{key}' stored.[/green]")


@app.command("vault-get")
def vault_get(
    key: str = typer.Argument(..., help="Secret key name."),
    show: bool = typer.Option(False, "--show", help="Print the full secret value to stdout (plaintext)."),
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c"),
) -> None:
    """Check whether a secret exists in the vault (redacted by default).

    Use --show to print the full plaintext value. This will be visible in
    your shell history, process list, and any log capture tools.
    """
    cfg = _load_or_default(config)
    from llmcouncil.adapters.vault import build_vault

    vault = build_vault(cfg.vault.backend, cfg.config_dir, cfg.vault.identity_file)
    value = vault.get(key)
    if value is None:
        console.print(f"[yellow]Secret '{key}' not found.[/yellow]")
        raise typer.Exit(1)
    if show:
        console.print(f"[yellow]WARNING: printing secret in plaintext.[/yellow]")
        typer.echo(value)
    else:
        redacted = value[:2] + "*" * max(0, len(value) - 6) + value[-4:] if len(value) > 6 else "****"
        console.print(f"Secret '{key}' exists. Value (redacted): [dim]{redacted}[/dim]")
        console.print("[dim]Use --show to print the full value.[/dim]")


@app.command("vault-delete")
def vault_delete(
    key: str = typer.Argument(..., help="Secret key name."),
    config: Path = typer.Option(_DEFAULT_CONFIG_FILE, "--config", "-c"),
) -> None:
    """Delete a secret from the vault."""
    cfg = _load_or_default(config)
    from llmcouncil.adapters.vault import build_vault

    vault = build_vault(cfg.vault.backend, cfg.config_dir, cfg.vault.identity_file)
    vault.delete(key)
    console.print(f"[green]Secret '{key}' deleted.[/green]")


if __name__ == "__main__":
    app()
