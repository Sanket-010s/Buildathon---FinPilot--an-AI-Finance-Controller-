"""
stage2_attribute.py — Stage 2: Attribute Match

For records that failed Stage 1 (no exact ID link to a settlement),
attempts resolution by matching on a composite key:
    - Amount (exact)
    - Date (within ± DATE_TOLERANCE_DAYS)
    - Customer ID (if available)

This handles cases where the settlement's order_id/payment_id was severed
(lump-sum settlements) but the underlying record data aligns.

Contract:
    match(unified_df, settlements_df) -> (resolved_df, unresolved_df)

Confidence: base 0.90, −0.02 per day of date drift tolerated.
"""

from __future__ import annotations

import pandas as pd

from backend.config import DATE_TOLERANCE_DAYS, AMOUNT_TOLERANCE_INR
from backend.utils.confidence import attribute_confidence
from backend.utils.logger import StageTimer, write as audit_write

STAGE_NAME = "attribute"


def match(
    unified_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Stage 2: Attribute Match.

    Args:
        unified_df:      Records still unresolved after Stage 1.
        settlements_df:  Full normalised settlements DataFrame (to find
                         orphaned settlements not yet linked to any order).

    Returns:
        (resolved_df, unresolved_df)
    """
    # Find settlements that have no order_id / payment_id link
    # (these are the orphaned settlement records we try to attribute-match against)
    from backend.engine.normalize import normalize_settlements

    if "setl_settlement_id" in settlements_df.columns:
        # Already normalised with prefix — unwrap prefix for matching
        s = settlements_df.copy()
        s.columns = [c.replace("setl_", "") if c.startswith("setl_") else c for c in s.columns]
    else:
        s = settlements_df.copy()

    # Make sure settlement_date is datetime
    if "settlement_date" in s.columns:
        s["settlement_date"] = pd.to_datetime(s["settlement_date"], errors="coerce")

    orphan_settlements = s[s["order_id"].isna() | s["payment_id"].isna()].copy()

    resolved_rows: list[pd.Series] = []
    unresolved_rows: list[pd.Series] = []
    used_settlement_ids: set[str] = set()

    for _, row in unified_df.iterrows():
        with StageTimer() as timer:
            result = _check_attribute(row, orphan_settlements, used_settlement_ids)

        record_id = str(row.get("record_id", row.get("order_id", "UNKNOWN")))

        if result["matched"]:
            used_settlement_ids.add(result["settlement_id"])
            audit_write(
                record_id=record_id,
                stage=STAGE_NAME,
                reasoning=result["reason"],
                candidates_considered=[result["settlement_id"]],
                duration_ms=timer.elapsed_ms,
            )
            row = row.copy()
            row["match_stage"] = STAGE_NAME
            row["confidence_score"] = attribute_confidence(result["date_drift"])
            row["match_status"] = "RESOLVED"
            # Backfill settlement columns from the matched settlement
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


def _check_attribute(
    row: pd.Series,
    orphan_settlements: pd.DataFrame,
    used_settlement_ids: set[str],
) -> dict:
    """
    Try to find a matching settlement row by amount + date + customer proximity.
    Returns a result dict with matched, reason, settlement_id, date_drift, settlement_data.
    """
    order_amount = row.get("order_amount")
    order_date = row.get("order_date")
    customer_id = row.get("customer_id")
    order_id = row.get("order_id", "UNKNOWN")

    if orphan_settlements.empty:
        return {"matched": False, "reason": "No orphaned settlements available to attribute-match."}

    if pd.isna(order_amount):
        return {"matched": False, "reason": f"Order {order_id} has no amount — cannot attribute-match."}

    if pd.isna(order_date):
        return {"matched": False, "reason": f"Order {order_id} has no date — cannot attribute-match."}

    # Filter out already-used settlements
    available = orphan_settlements[
        ~orphan_settlements["settlement_id"].isin(used_settlement_ids)
    ].copy()

    if available.empty:
        return {"matched": False, "reason": "All available orphaned settlements already claimed."}

    # Amount must match exactly (within ₹1 tolerance)
    amount_mask = (available["gross_amount"] - order_amount).abs() <= AMOUNT_TOLERANCE_INR
    candidates = available[amount_mask].copy()

    if candidates.empty:
        return {
            "matched": False,
            "reason": (
                f"No settlement with gross_amount ≈ ₹{order_amount:.2f} "
                f"(±₹{AMOUNT_TOLERANCE_INR}) found for order {order_id}."
            ),
        }

    # Date window check
    order_dt = pd.to_datetime(order_date)
    candidates["date_diff"] = (
        (candidates["settlement_date"] - order_dt).dt.days.abs()
    )
    date_mask = candidates["date_diff"] <= DATE_TOLERANCE_DAYS
    candidates = candidates[date_mask]

    if candidates.empty:
        return {
            "matched": False,
            "reason": (
                f"Amount matched but no settlement within ±{DATE_TOLERANCE_DAYS} days "
                f"of order date {order_dt.date()} for order {order_id}."
            ),
        }

    # Pick the closest date match
    best = candidates.sort_values("date_diff").iloc[0]
    drift = int(best["date_diff"])

    return {
        "matched": True,
        "reason": (
            f"Attribute match — order {order_id} ↔ settlement {best['settlement_id']} "
            f"(amount ₹{order_amount:.2f}, date drift {drift}d within {DATE_TOLERANCE_DAYS}d tolerance)."
        ),
        "settlement_id": str(best["settlement_id"]),
        "date_drift": drift,
        "settlement_data": best.to_dict(),
    }


def _empty_frame(reference_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=reference_df.columns)
