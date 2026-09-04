"""
stage3_fuzzy.py — Stage 3: Fuzzy Match

Uses RapidFuzz to find approximate string matches between merchant reference
strings, narration fields, or order IDs that have minor variations (typos,
formatting differences, extra spaces).

Applied to records that couldn't be resolved by exact or attribute matching.

Contract:
    match(unified_df, settlements_df) -> (resolved_df, unresolved_df)

Threshold: FUZZY_THRESHOLD (default 85 similarity score).
Confidence: (similarity / 100) × 0.85.
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz

from backend.config import FUZZY_THRESHOLD
from backend.utils.confidence import fuzzy_confidence
from backend.utils.logger import StageTimer, write as audit_write

STAGE_NAME = "fuzzy"


def match(
    unified_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Stage 3: Fuzzy Match.

    Args:
        unified_df:      Records still unresolved after Stage 2.
        settlements_df:  Full normalised settlements DataFrame.

    Returns:
        (resolved_df, unresolved_df)
    """
    if "setl_settlement_id" in settlements_df.columns:
        s = settlements_df.copy()
        s.columns = [c.replace("setl_", "") if c.startswith("setl_") else c for c in s.columns]
    else:
        s = settlements_df.copy()

    resolved_rows: list[pd.Series] = []
    unresolved_rows: list[pd.Series] = []
    used_settlement_ids: set[str] = set()

    for _, row in unified_df.iterrows():
        with StageTimer() as timer:
            result = _check_fuzzy(row, s, used_settlement_ids)

        record_id = str(row.get("record_id", row.get("order_id", "UNKNOWN")))

        if result["matched"]:
            used_settlement_ids.add(result["settlement_id"])
            confidence = fuzzy_confidence(result["similarity"])
            audit_write(
                record_id=record_id,
                stage=STAGE_NAME,
                reasoning=result["reason"],
                candidates_considered=[result["settlement_id"]],
                duration_ms=timer.elapsed_ms,
            )
            row = row.copy()
            row["match_stage"] = STAGE_NAME
            row["confidence_score"] = confidence
            row["match_status"] = "RESOLVED"
            for col, val in result["settlement_data"].items():
                row[f"setl_{col}"] = val
            resolved_rows.append(row)
        else:
            audit_write(
                record_id=record_id,
                stage=STAGE_NAME,
                reasoning=result["reason"],
                duration_ms=timer.elapsed_ms,
            )
            unresolved_rows.append(row)

    resolved_df = pd.DataFrame(resolved_rows) if resolved_rows else _empty_frame(unified_df)
    unresolved_df = pd.DataFrame(unresolved_rows) if unresolved_rows else _empty_frame(unified_df)

    return resolved_df, unresolved_df


def _build_reference_string(row: pd.Series) -> str:
    """
    Build a composite reference string from available text fields for fuzzy comparison.
    Priority: merchant_ref → narration → order_id.
    """
    parts = []
    for field in ["merchant_ref", "narration", "order_id"]:
        val = row.get(field)
        if val and not (isinstance(val, float) and pd.isna(val)):
            parts.append(str(val).strip())
    return " ".join(parts) if parts else ""


def _build_settlement_ref(row: pd.Series) -> str:
    """Build a reference string from settlement fields."""
    parts = []
    for field in ["settlement_narration", "settlement_id", "order_id"]:
        val = row.get(field)
        if val and not (isinstance(val, float) and pd.isna(val)):
            parts.append(str(val).strip())
    return " ".join(parts) if parts else ""


def _check_fuzzy(
    row: pd.Series,
    settlements_df: pd.DataFrame,
    used_settlement_ids: set[str],
) -> dict:
    """
    Compute fuzzy similarity between this record's reference string and all
    available settlement reference strings.
    """
    order_id = row.get("order_id", "UNKNOWN")
    order_ref = _build_reference_string(row)

    if not order_ref:
        return {
            "matched": False,
            "reason": f"Order {order_id} has no reference string for fuzzy matching.",
        }

    available = settlements_df[
        ~settlements_df["settlement_id"].isin(used_settlement_ids)
    ].copy()

    if available.empty:
        return {"matched": False, "reason": "No settlements available for fuzzy matching."}

    best_score = 0.0
    best_idx = None

    for idx, s_row in available.iterrows():
        s_ref = _build_settlement_ref(s_row)
        if not s_ref:
            continue
        score = fuzz.token_sort_ratio(order_ref, s_ref)
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_idx is None or best_score < FUZZY_THRESHOLD:
        return {
            "matched": False,
            "reason": (
                f"Fuzzy match — best similarity {best_score:.0f} "
                f"(below threshold {FUZZY_THRESHOLD}) for order {order_id}."
            ),
        }

    best = available.loc[best_idx]
    return {
        "matched": True,
        "reason": (
            f"Fuzzy match — order {order_id} ↔ settlement {best['settlement_id']} "
            f"(similarity score {best_score:.0f} ≥ threshold {FUZZY_THRESHOLD})."
        ),
        "settlement_id": str(best["settlement_id"]),
        "similarity": best_score,
        "settlement_data": best.to_dict(),
    }


def _empty_frame(reference_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=reference_df.columns)
