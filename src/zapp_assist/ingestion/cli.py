"""`zapp-ingest` — one-command knowledge ingestion (spec 001, FR-023).

    zapp-ingest build              # rebuild the KB from cache (offline, deterministic, keyless)
    zapp-ingest build --refresh    # enrich cache-missing docs via the provider (needs a key)
    zapp-ingest validate           # structural + coverage checks only (CI gate; non-zero on error)

Exits non-zero when validation fails, so it drops straight into CI.
"""

from __future__ import annotations

import typer

from ..config import load_config
from .pipeline import BuildReport, build_kb, load_sources
from .validate import ValidationReport, validate_documents

app = typer.Typer(help="Zapp Assist knowledge ingestion pipeline.", no_args_is_help=True)


def _print_validation(report: ValidationReport) -> None:
    for issue in report.issues:
        marker = "✗" if issue.level == "error" else "!"
        typer.echo(f"  {marker} [{issue.level}] {issue.doc_id}: {issue.message}")
    if report.ok and not report.warnings:
        typer.echo("  ✓ all documents valid")


@app.command()
def build(
    refresh: bool = typer.Option(
        False, "--refresh", help="Enrich cache-missing docs via the configured LLM (needs a key)."
    ),
    n_questions: int = typer.Option(4, "--questions", help="HyPE questions per document."),
) -> None:
    """Validate, enrich, and rebuild the knowledge base."""

    cfg = load_config()
    llm = None
    if refresh:
        from ..agent import _default_llm  # lazy: only a --refresh run needs a live provider

        llm = _default_llm(cfg)

    report: BuildReport = build_kb(
        supported_langs=cfg.languages.supported,
        llm=llm,
        model=cfg.models.primary,
        n_questions=n_questions,
        refresh=refresh,
    )

    if not report.ok:
        typer.echo("Build FAILED — validation errors:")
        _print_validation(report.validation)
        raise typer.Exit(code=1)

    typer.echo(
        f"Built {report.total} documents "
        f"(cache={report.from_cache}, adopted={report.adopted}, "
        f"generated={report.generated}, missing={report.missing})."
    )
    if report.cost_usd:
        typer.echo(f"Enrichment cost: ${report.cost_usd:.4f}")
    if report.validation.warnings:
        typer.echo("Warnings:")
        _print_validation(report.validation)
    if report.missing:
        typer.echo(f"! {report.missing} document(s) have no questions (use --refresh + a key).")


@app.command()
def validate() -> None:
    """Run structural + coverage checks only; exit non-zero on any error."""

    cfg = load_config()
    report = validate_documents(load_sources(), supported_langs=cfg.languages.supported)
    _print_validation(report)
    raise typer.Exit(code=0 if report.ok else 1)


if __name__ == "__main__":
    app()
