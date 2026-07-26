"""Typer CLI: `chat` (interactive multi-turn) and `turn` (one-shot; prints the JSON contract)."""

from __future__ import annotations

import typer
from rich.console import Console

from .agent import Agent

app = typer.Typer(add_completion=False, help="Zapp Assist — conversational support agent.")
console = Console()


@app.command()
def turn(
    session: str = typer.Option("demo", "--session", help="Session id."),
    text: str = typer.Option(..., "--text", help="User message for this turn."),
) -> None:
    """Run a single turn and print the canonical JSON contract."""

    agent = Agent.create()
    result = agent.run_turn(session, text)
    console.print_json(result.model_dump_json())


@app.command()
def chat(session: str = typer.Option("demo", "--session", help="Session id.")) -> None:
    """Interactive multi-turn session (keeps active_lang + memory). Ctrl-D / 'exit' to quit."""

    agent = Agent.create()
    console.print("[bold cyan]Zapp Assist[/bold cyan] — type 'exit' to quit.")
    while True:
        try:
            text = console.input("[bold green]you>[/bold green] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if text.strip().lower() in {"exit", "quit"}:
            break
        result = agent.run_turn(session, text)
        flag = " [yellow](needs review)[/yellow]" if result.needs_review else ""
        console.print(f"[bold blue]zapp>[/bold blue] {result.reply}{flag}")


if __name__ == "__main__":
    app()
