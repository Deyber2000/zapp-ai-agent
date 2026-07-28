"""Structured logging (Constitution XI): one JSON event per turn, emitted from `run_turn`.

`structlog` was a declared dependency with no call sites — the per-turn `Trace` was built and then
dropped, so nothing an operator could `grep` was ever emitted. `run_turn` now logs a single
structured line per turn (ids, language, intent, review flag, tokens, cost, latency, guardrail
actions). Output is JSON on stderr; a host application that has already configured `structlog` keeps
its own configuration, and pytest captures the stream so tests stay quiet.
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

if not structlog.is_configured():
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,  # keep structlog.testing.capture_logs able to intercept
    )


def get_logger(name: str = "zapp") -> Any:
    """A structlog logger. Lazy proxy — resolves processors per call so tests can capture it."""

    return structlog.get_logger(name)
