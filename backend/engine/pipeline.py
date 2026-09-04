"""
pipeline.py — Reconciliation Pipeline Orchestrator for FinPilot.

Runs all 5 stages in strict order per record:
    Stage 1: Exact Match
    Stage 2: Attribute Match
    Stage 3: Fuzzy Match
    Stage 4: Arithmetic Verification
    Stage 5: AI Explanation (last resort)

Records are resolved at the first stage that succeeds.
Any record surviving all 5 stages becomes a visible EXCEPTION — never dropped.

Public API:
    run_pipeline(data_dir) -> PipelineResult
    run_pipeline_from_dfs(orders_df, payments_df, settlements_df, refunds_df) -> PipelineResult
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from backend.engine import (
    normalize,
    stage1_exact,
    stage2_attribute,
    stage3_fuzzy,
    stage4_arithmetic,
    stage5_ai,
)
from backend.utils.logger import flush_buffer

DATA_DIR = Path(__file__).parent.parent.parent / "data"


@dataclass
class PipelineResult:
    """Holds the full output of one reconciliation run."""

    # Per-stage resolved DataFrames
    resolved_exact: pd.DataFrame = field(default_factory=pd.DataFrame)
    resolved_attribute: pd.DataFrame = field(default_factory=pd.DataFrame)
    resolved_fuzzy: pd.DataFrame = field(default_factory=pd.DataFrame)
    resolved_arithmetic: pd.DataFrame = field(default_factory=pd.DataFrame)
    ai_explained: pd.DataFrame = field(default_factory=pd.DataFrame)
    exceptions: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Timing
    duration_seconds: float = 0.0

    # Audit log entries (raw dicts, to be persisted by database layer)
    audit_entries: list[dict] = field(default_factory=list)

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def all_resolved(self) -> pd.DataFrame:
        """All RESOLVED records (stages 1–4). AI-explained are still exceptions."""
        frames = [
            self.resolved_exact,
            self.resolved_attribute,
            self.resolved_fuzzy,
            self.resolved_arithmetic,
        ]
        non_empty = [f for f in frames if not f.empty]
        if not non_empty:
            return pd.DataFrame()
        return pd.concat(non_empty, ignore_index=True)

    @property
    def all_exceptions(self) -> pd.DataFrame:
        """All exception records: AI-explained + fully unresolved."""
        frames = [self.ai_explained, self.exceptions]
        non_empty = [f for f in frames if not f.empty]
        if not non_empty:
            return pd.DataFrame()
        return pd.concat(non_empty, ignore_index=True)

    @property
    def total_records(self) -> int:
        return (
            len(self.resolved_exact)
            + len(self.resolved_attribute)
            + len(self.resolved_fuzzy)
            + len(self.resolved_arithmetic)
            + len(self.ai_explained)
            + len(self.exceptions)
        )

    @property
    def total_resolved(self) -> int:
        return (
            len(self.resolved_exact)
            + len(self.resolved_attribute)
            + len(self.resolved_fuzzy)
            + len(self.resolved_arithmetic)
        )

    @property
    def total_exceptions(self) -> int:
        return len(self.ai_explained) + len(self.exceptions)

    @property
    def match_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return round(self.total_resolved / self.total_records, 4)

    def summary(self) -> dict:
        """Return a summary dict suitable for the /reconcile/summary API response."""
        return {
            "total_records": self.total_records,
            "resolved": self.total_resolved,
            "exceptions": self.total_exceptions,
            "match_rate": self.match_rate,
            "duration_seconds": round(self.duration_seconds, 3),
            "by_stage": {
                "exact": len(self.resolved_exact),
                "attribute": len(self.resolved_attribute),
                "fuzzy": len(self.resolved_fuzzy),
                "arithmetic": len(self.resolved_arithmetic),
                "ai_explained": len(self.ai_explained),
                "unresolved": len(self.exceptions),
            },
        }


def run_pipeline(data_dir: str | Path = DATA_DIR) -> PipelineResult:
    """
    Load CSVs from data_dir, normalise, and run the full 5-stage pipeline.
    """
    orders_df, payments_df, settlements_df, refunds_df = normalize.load_and_normalize(data_dir)
    return run_pipeline_from_dfs(orders_df, payments_df, settlements_df, refunds_df)


def run_pipeline_from_dfs(
    orders_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
    refunds_df: pd.DataFrame,
) -> PipelineResult:
    """
    Run the full 5-stage reconciliation pipeline on pre-loaded DataFrames.
    """
    start_time = time.perf_counter()

    # ── Step 0: Build unified view ────────────────────────────────────────────
    unified = normalize.unify(orders_df, payments_df, settlements_df, refunds_df)
    print(f"[Pipeline] Unified {len(unified)} records for reconciliation.")

    # Keep raw settlement/payment/refund DFs for stages that need to search them
    raw_settlements = settlements_df.copy()
    raw_payments = payments_df.copy()
    raw_refunds = refunds_df.copy()

    # ── Stage 1: Exact Match ──────────────────────────────────────────────────
    resolved_exact, unresolved = stage1_exact.match(unified)
    print(f"[Stage 1] Exact:        {len(resolved_exact):>4} resolved | {len(unresolved):>4} remaining")

    # ── Stage 2: Attribute Match ──────────────────────────────────────────────
    resolved_attr, unresolved = stage2_attribute.match(unresolved, raw_settlements)
    print(f"[Stage 2] Attribute:    {len(resolved_attr):>4} resolved | {len(unresolved):>4} remaining")

    # ── Stage 3: Fuzzy Match ──────────────────────────────────────────────────
    resolved_fuzzy, unresolved = stage3_fuzzy.match(unresolved, raw_settlements)
    print(f"[Stage 3] Fuzzy:        {len(resolved_fuzzy):>4} resolved | {len(unresolved):>4} remaining")

    # ── Stage 4: Arithmetic Verification ─────────────────────────────────────
    resolved_arith, unresolved = stage4_arithmetic.verify(unresolved, raw_settlements)
    print(f"[Stage 4] Arithmetic:   {len(resolved_arith):>4} resolved | {len(unresolved):>4} remaining")

    # ── Stage 5: AI Explanation ───────────────────────────────────────────────
    ai_explained, exceptions = stage5_ai.explain(
        unresolved, raw_settlements, raw_payments, raw_refunds
    )
    print(
        f"[Stage 5] AI:           {len(ai_explained):>4} explained | "
        f"{len(exceptions):>4} unknown exceptions"
    )

    duration = time.perf_counter() - start_time

    # ── Collect audit log ─────────────────────────────────────────────────────
    audit_entries = flush_buffer()

    result = PipelineResult(
        resolved_exact=resolved_exact,
        resolved_attribute=resolved_attr,
        resolved_fuzzy=resolved_fuzzy,
        resolved_arithmetic=resolved_arith,
        ai_explained=ai_explained,
        exceptions=exceptions,
        duration_seconds=duration,
        audit_entries=audit_entries,
    )

    summary = result.summary()
    print(
        f"\n[Pipeline] Complete in {duration:.2f}s — "
        f"{summary['resolved']}/{summary['total_records']} resolved "
        f"({summary['match_rate']*100:.1f}%), "
        f"{summary['exceptions']} exceptions."
    )

    return result
