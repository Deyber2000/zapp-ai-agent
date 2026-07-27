"""Typer CLI: `chat` (interactive multi-turn) and `turn` (one message; prints the JSON contract).

Both persist session state to `.zapp_sessions/` (a `FileSessionStore`), so a conversation is
multi-turn **across invocations**: reuse `--session <id>` to continue. When `--session` is omitted a
new id is generated and printed — pass it back on the next `turn` to keep the thread.
"""

from __future__ import annotations

from uuid import uuid4

import typer
from rich.console import Console

from .agent import Agent
from .config import REPO_ROOT
from .memory.session_store import FileSessionStore

app = typer.Typer(add_completion=False, help="Zapp Assist — conversational support agent.")
console = Console()

_SESSION_DIR = REPO_ROOT / ".zapp_sessions"


@app.command()
def turn(
    text: str = typer.Option(..., "--text", help="User message for this turn."),
    session: str | None = typer.Option(
        None, "--session", help="Session id to continue; a new one is generated if omitted."
    ),
) -> None:
    """Run a single turn and print the canonical JSON contract (reuse --session for multi-turn)."""

    session_id = session or uuid4().hex
    agent = Agent.create(store=FileSessionStore(_SESSION_DIR))
    result = agent.run_turn(session_id, text)
    console.print(f"[dim]session: {session_id}[/dim]")
    console.print_json(result.model_dump_json())


@app.command()
def chat(
    session: str | None = typer.Option(
        None, "--session", help="Session id to continue; a new one is generated if omitted."
    ),
) -> None:
    """Interactive multi-turn session (persistent; keeps active_lang + memory). Ctrl-D to quit."""

    session_id = session or uuid4().hex
    agent = Agent.create(store=FileSessionStore(_SESSION_DIR))
    console.print(
        f"[bold cyan]Zapp Assist[/bold cyan] [dim]session {session_id}[/dim] — 'exit' to quit"
    )
    while True:
        try:
            text = console.input("[bold green]you>[/bold green] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if text.strip().lower() in {"exit", "quit"}:
            break
        result = agent.run_turn(session_id, text)
        flag = " [yellow](needs review)[/yellow]" if result.needs_review else ""
        console.print(f"[bold blue]zapp>[/bold blue] {result.reply}{flag}")


if __name__ == "__main__":
    app()
