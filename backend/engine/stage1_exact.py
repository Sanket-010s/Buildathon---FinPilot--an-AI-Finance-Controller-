"""
stage1_exact.py — Stage 1: Exact Match

Attempts to resolve records by verifying that transaction/reference IDs
match exactly across orders, payments, and settlements.

Contract:
    match(unified_df) -> (resolved_df, unresolved_df)

A record is RESOLVED at this stage if:
    - order_id links to a payment (pay_payment_id is not null)
    - that payment links to a settlement (setl_settlement_id is not null)
    - payment status is 'captured' (or equivalent)

Confidence: fixed at 1.0 (no inference involved).
"""

from __future__ import annotations

import pandas as pd

from backend.utils.confidence import exact_confidence
from backend.utils.logger import StageTimer, write as audit_write

STAGE_NAME = "exact"


def match(unified_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Stage 1: Exact Match.

    Args:
        unified_df: output of normalize.unify() — one row per order,
                    with payment and settlement columns joined.

    Returns:
        (resolved_df, unresolved_df) — both are subsets of unified_df
        with additional columns:
            match_stage      : "exact"
            confidence_score : 1.0
            match_status     : "RESOLVED"
    """
    resolved_rows = []
    unresolved_rows = []

    for _, row in unified_df.iterrows():
        with StageTimer() as timer:
            resolution = _check_exact(row)

        record_id = row.get("record_id", row.get("order_id", "UNKNOWN"))

        if resolution["matched"]:
            audit_write(
                record_id=str(record_id),
                stage=STAGE_NAME,
                reasoning=resolution["reason"],
                duration_ms=timer.elapsed_ms,
            )
            row = row.copy()
            row["match_stage"] = STAGE_NAME
            row["confidence_score"] = exact_confidence()
            row["match_status"] = "RESOLVED"
            resolved_rows.append(row)
        else:
            audit_write(
                record_id=str(record_id),
                stage=STAGE_NAME,
                reasoning=resolution["reason"],
                duration_ms=timer.elapsed_ms,
            )
            unresolved_rows.append(row)

    resolved_df = pd.DataFrame(resolved_rows) if resolved_rows else _empty_frame(unified_df)
    unresolved_df = pd.DataFrame(unresolved_rows) if unresolved_rows else _empty_frame(unified_df)

    return resolved_df, unresolved_df


def _check_exact(row: pd.Series) -> dict:
    """
    Evaluate a single row for exact match eligibility.
    Returns a dict: {matched: bool, reason: str}
    """
    order_id = row.get("order_id")
    pay_id = row.get("pay_payment_id")
    setl_id = row.get("setl_settlement_id")
    pay_status = str(row.get("pay_payment_status", "")).lower()
    order_status = str(row.get("order_status", "")).lower()

    # Silent failure check: order says failed but payment was captured
    # We surface these as a special case — not silently auto-resolved
    if order_status == "failed" and pay_status == "captured":
        return {
            "matched": False,
            "reason": (
                f"Silent failure detected — order status is 'failed' "
                f"but payment {pay_id} was captured. Needs human review."
            ),
        }

    # Core exact match: all three IDs must be present and payment captured
    if not order_id:
        return {"matched": False, "reason": "Missing order_id — cannot attempt exact match."}

    if not pay_id or pd.isna(pay_id):
        return {"matched": False, "reason": f"No linked payment found for order {order_id}."}

    if pay_status not in ("captured", "paid", "success", "settled"):
        return {
            "matched": False,
            "reason": (
                f"Payment {pay_id} status is '{pay_status}' — "
                "not a successful capture; cannot confirm as exact match."
            ),
        }

    if not setl_id or pd.isna(setl_id):
        return {
            "matched": False,
            "reason": (
                f"Payment {pay_id} found for order {order_id}, "
                "but no linked settlement record exists."
            ),
        }

    # All checks passed
    return {
        "matched": True,
        "reason": (
            f"Exact match confirmed — order {order_id} ↔ payment {pay_id} "
            f"↔ settlement {setl_id}. All IDs align, payment captured."
        ),
    }


def _empty_frame(reference_df: pd.DataFrame) -> pd.DataFrame:
    """Return an empty DataFrame with the same columns as reference_df."""
    return pd.DataFrame(columns=reference_df.columns)
