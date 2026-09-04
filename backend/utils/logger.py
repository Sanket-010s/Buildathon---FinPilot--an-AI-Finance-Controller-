"""
logger.py — Audit log writer for FinPilot.

Every reconciliation decision is recorded to the audit_log table in SQLite.
This module provides a simple write-only interface used by each pipeline stage.

The log is what powers GET /records/{id}/audit and is what a CFO or auditor
would pull to defend the books during a compliance review.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

# stdlib logger for stdout debugging during development
_log = logging.getLogger("finpilot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


# ── In-memory buffer (flushed to DB by the pipeline orchestrator) ─────────────
_audit_buffer: list[dict] = []


def write(
    record_id: str,
    stage: str,
    reasoning: str,
    candidates_considered: list[str] | None = None,
    ai_explanation: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """
    Append one audit entry to the in-memory buffer.

    Args:
        record_id:              The order/record being processed.
        stage:                  Pipeline stage name (e.g., "exact", "attribute", "ai").
        reasoning:              One-line human-readable reason for pass/fail at this stage.
        candidates_considered:  List of candidate record IDs the stage considered (if any).
        ai_explanation:         Full text of the AI's explanation (Stage 5 only).
        duration_ms:            Time taken for this stage check in milliseconds.
    """
    entry = {
        "record_id": record_id,
        "stage": stage,
        "reasoning": reasoning,
        "candidates_considered": json.dumps(candidates_considered or []),
        "ai_explanation": ai_explanation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
    }
    _audit_buffer.append(entry)
    _log.debug("[AUDIT] %s | %s | %s", record_id, stage, reasoning)


def flush_buffer() -> list[dict]:
    """
    Return the current audit buffer and clear it.
    Called by the pipeline orchestrator after each run to persist to SQLite.
    """
    global _audit_buffer
    entries = list(_audit_buffer)
    _audit_buffer = []
    return entries


def get_buffer() -> list[dict]:
    """Return the current buffer without clearing (for inspection)."""
    return list(_audit_buffer)


class StageTimer:
    """
    Context manager for timing a pipeline stage.

    Usage:
        with StageTimer() as t:
            ... stage logic ...
        elapsed_ms = t.elapsed_ms
    """
    def __init__(self):
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
