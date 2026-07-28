"""`zapp-eval` — run the evaluation suite and emit one report (spec 004).

One command: load the dataset + thresholds, run the agent over every case, compute metrics, write
report.json + report.md, print a summary, and exit non-zero if any metric fails (CI gate).

The **deterministic core** (scripted model + rule-based judge, bm25 retrieval) always runs, keyless
and reproducible, so it can gate CI anywhere. When an API key is present *and* deepeval is
installed, a **live LLM-judged quality tier** (LLM-as-judge + deepeval faithfulness / contextual
relevancy over the real agent's outputs) is added automatically — no flag. The tier's metrics are
reported alongside the core but excluded from the committed-report drift guard (LLM judgments aren't
byte-reproducible).
"""

from __future__ import annotations

from pathlib import Path

import typer

from zapp_assist.config import get_settings, load_config

from .models import MetricResult, load_dataset, load_thresholds
from .quality_tier import live_tier_available, run_quality_tier
from .report import build_report, render_markdown, write_report
from .runner import run_dataset

app = typer.Typer(add_completion=False, help="Zapp Assist evaluation suite.")


@app.command()
def main(
    dataset: str | None = typer.Option(None, help="Dataset directory."),
    config: str | None = typer.Option(None, help="Thresholds YAML."),
    out: str | None = typer.Option(None, help="Report output directory."),
) -> None:
    """Run the evaluation and write the report; exit non-zero on any threshold failure."""

    cases = load_dataset(dataset)
    thresholds = load_thresholds(config)
    records = run_dataset(cases)  # deterministic core — always runs, keyless

    extra: list[MetricResult] = []
    note = "deterministic (scripted model + rule-based judge)"
    settings = get_settings()
    if live_tier_available(settings):
        typer.echo("Key present — running live tier: task success + LLM judge (deepeval optional).")
        extra = run_quality_tier(cases, load_config(), settings, thresholds)
        if extra:
            note = "deterministic core + live tier (task success + LLM judge)"

    report = build_report(records, cases, thresholds, extra_metrics=extra, note=note)
    write_report(report, Path(out) if out else None)

    typer.echo(render_markdown(report))
    raise typer.Exit(code=0 if report.overall_passed else 1)


if __name__ == "__main__":
    app()
