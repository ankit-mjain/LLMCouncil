"""TUI dashboard — full Textual implementation (M6)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from llmcouncil.config import AppConfig
from llmcouncil.tui.events import CouncilEvent
from llmcouncil.tui.pubsub import EventBus

_ROLE_COLOR: dict[str, str] = {
    "draft": "green",
    "critique": "yellow",
    "dissent": "red",
    "vote": "cyan",
    "verdict": "bold yellow",
}


class CouncilTUI(App[None]):
    """Textual TUI dashboard for LLMCouncil."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1 4;
        grid-rows: 3 1fr 3 3;
    }
    #panels {
        layout: horizontal;
    }
    #seats {
        width: 36;
        border: solid $accent;
        padding: 0 1;
    }
    #transcript {
        border: solid $primary;
        padding: 0 1;
    }
    #status {
        height: 3;
        border: solid $success;
        padding: 0 1;
        content-align: left middle;
    }
    Input {
        height: 3;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "show_cost", "Cost"),
        ("m", "show_memory", "Memory"),
        ("s", "pause_session", "Pause"),
    ]

    def __init__(self, cfg: AppConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._bus = EventBus()
        self._round: int = 0
        self._session_id: str = ""
        self._total_cost: float = 0.0
        self._verdict_rendered: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panels"):
            yield Static("", id="seats")
            yield RichLog(id="transcript", highlight=True, markup=True)
        yield Static("[dim]Ready.[/dim]  Type a query below and press Enter.", id="status")
        yield Input(placeholder="Ask a question… (prefix /Council for council mode)")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_seats()
        self.set_interval(0.1, self._poll_events)
        # Register the bus with the orchestrator.
        from llmcouncil.council.orchestrator import set_event_bus
        set_event_bus(self._bus)

    def on_unmount(self) -> None:
        from llmcouncil.council.orchestrator import set_event_bus
        set_event_bus(None)

    # ------------------------------------------------------------------
    # Seats / cost panel
    # ------------------------------------------------------------------

    def _refresh_seats(self) -> None:
        lines = ["[bold]Seats[/bold]"]
        for seat in self.cfg.council.seats:
            role = seat.role.replace("_", " ").title()
            lines.append(f"● {seat.seat_id}  {role:<18} {seat.model}")
        lines += [
            "",
            "[bold]Cost[/bold]",
            f"session  ${self._total_cost:.4f} / ${self.cfg.budget.per_session_usd:.2f}",
        ]
        self.query_one("#seats", Static).update("\n".join(lines))

    # ------------------------------------------------------------------
    # Event polling
    # ------------------------------------------------------------------

    def _poll_events(self) -> None:
        for event in self._bus.drain():
            self._handle_event(event)

    def _handle_event(self, event: CouncilEvent) -> None:
        log = self.query_one("#transcript", RichLog)
        status = self.query_one("#status", Static)

        if event.kind == "round_change":
            self._round = event.payload.get("round", 0)
            self._session_id = event.session_id
            sid_short = event.session_id[:8]
            status.update(
                f"[dim]session {sid_short}[/dim]  "
                f"[bold]Round {self._round} in flight…[/bold]"
            )

        elif event.kind == "transcript_entry":
            kind = event.payload.get("kind", "?")
            seat_id = event.payload.get("seat_id", 0)
            content = (event.payload.get("content") or "")[:300]
            color = _ROLE_COLOR.get(kind, "white")
            log.write(
                f"[dim]r{self._round}[/dim]  [{color}]{kind}[/{color}]"
                f"  [dim]seat {seat_id}[/dim]:  {content}"
            )

        elif event.kind == "cost_update":
            self._total_cost += event.payload.get("usd", 0.0)
            self._refresh_seats()

        elif event.kind == "verdict":
            self._verdict_rendered = True
            text = event.payload.get("text", "")
            mechanism = event.payload.get("mechanism", "")
            log.write("")
            log.write(f"[bold yellow]{'═' * 50}[/bold yellow]")
            log.write(f"[bold yellow]  VERDICT  ({mechanism})[/bold yellow]")
            log.write(f"[bold yellow]{'═' * 50}[/bold yellow]")
            log.write(text)
            log.write("")
            status.update("[bold green]Verdict delivered.[/bold green]  Type another query to continue.")

        elif event.kind == "notification":
            self.notify(
                event.payload.get("message", ""),
                title=event.payload.get("title", "LLMCouncil"),
            )

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        event.input.clear()
        log = self.query_one("#transcript", RichLog)
        status = self.query_one("#status", Static)
        log.write(f"\n[bold cyan]> {query}[/bold cyan]\n")
        status.update("[bold]Processing…[/bold]")
        self._verdict_rendered = False
        self.run_worker(self._run_query(query), exclusive=True)

    async def _run_query(self, query: str) -> None:
        from llmcouncil.agent import dispatch

        try:
            result = await dispatch(query, self.cfg)
        except Exception as exc:  # noqa: BLE001
            log = self.query_one("#transcript", RichLog)
            log.write(f"[bold red]Error:[/bold red] {exc}")
            self.query_one("#status", Static).update("[bold red]Error — see transcript.[/bold red]")
            return

        # For single-shot responses (no verdict event), show the result directly.
        if not self._verdict_rendered:
            log = self.query_one("#transcript", RichLog)
            log.write(f"\n[bold]Answer:[/bold]\n{result}\n")
        self.query_one("#status", Static).update(
            "[bold green]Done.[/bold green]  Type another query to continue."
        )

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    def action_show_cost(self) -> None:
        self.notify(
            f"Session: ${self._total_cost:.4f} / ${self.cfg.budget.per_session_usd:.2f}",
            title="Cost",
        )

    def action_show_memory(self) -> None:
        self.notify("Memory recall not yet wired in TUI (M8).", title="Memory")

    def action_pause_session(self) -> None:
        self.notify("Session pause not yet implemented.", title="Pause")
