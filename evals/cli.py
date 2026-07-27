"""`zapp-eval` — run the evaluation suite and emit one report (spec 004).

One command: load the dataset + thresholds, run the agent over every case, compute metrics, write
report.json + report.md, print a summary, and exit non-zero if any metric fails (CI gate).
Deterministic by default (scripted per-case model + rule-based judge). `--live` is reserved for a
real provider run (US3+; keyed).
"""

from __future__ import annotations

from pathlib import Path

import typer

from .models import load_dataset, load_thresholds
from .report import build_report, render_markdown, write_report
from .runner import run_dataset

app = typer.Typer(add_completion=False, help="Zapp Assist evaluation suite.")


@app.command()
def main(
    dataset: str | None = typer.Option(None, help="Dataset directory."),
    config: str | None = typer.Option(None, help="Thresholds YAML."),
    out: str | None = typer.Option(None, help="Report output directory."),
    live: bool = typer.Option(False, "--live", help="Run against a real provider (needs a key)."),
) -> None:
    """Run the evaluation and write the report; exit non-zero on any threshold failure."""

    cases = load_dataset(dataset)
    thresholds = load_thresholds(config)
    note = "live (real provider)" if live else "deterministic (scripted model + rule-based judge)"

    records = run_dataset(cases)
    report = build_report(records, cases, thresholds, note=note)
    write_report(report, Path(out) if out else None)

    typer.echo(render_markdown(report))
    raise typer.Exit(code=0 if report.overall_passed else 1)


if __name__ == "__main__":
    app()
