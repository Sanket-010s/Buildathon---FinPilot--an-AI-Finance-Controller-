"""
stage4_arithmetic.py — Stage 4: Arithmetic Verification

For records where no direct ID or fuzzy link can be established,
checks whether the settlement net amount equals the expected net
computed from the order data.

Formula:
    Expected Net = Order Amount − MDR Fee − GST on MDR Fee − Refunds
    MDR Fee      = Order Amount × MDR_RATE (2%)
    GST on MDR   = MDR Fee × GST_RATE (18%)

Tolerance: AMOUNT_TOLERANCE_INR (default ₹1.0)

If abs(actual_net − expected_net) ≤ tolerance → RESOLVED (Arithmetic).

Contract:
    verify(unified_df, settlements_df) -> (resolved_df, unresolved_df)

Confidence: 0.95 base, −0.05 if full tolerance band used.
"""

from __future__ import annotations

import pandas as pd

from backend.config import AMOUNT_TOLERANCE_INR, MDR_RATE, GST_ON_MDR_RATE
from backend.utils.confidence import arithmetic_confidence
from backend.utils.logger import StageTimer, write as audit_write

STAGE_NAME = "arithmetic"


def verify(
    unified_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Stage 4: Arithmetic Verification.

    Args:
        unified_df:      Records still unresolved after Stage 3.
        settlements_df:  Full normalised settlements DataFrame.

    Returns:
        (resolved_df, unresolved_df)
    """
    if "setl_settlement_id" in settlements_df.columns:
        s = settlements_df.copy()
        s.columns = [c.replace("setl_", "") if c.startswith("setl_") else c for c in s.columns]
    else:
        s = settlements_df.copy()

    # Convert settlement_date to datetime if needed
    if "settlement_date" in s.columns:
        s["settlement_date"] = pd.to_datetime(s["settlement_date"], errors="coerce")

    resolved_rows: list[pd.Series] = []
    unresolved_rows: list[pd.Series] = []
    used_settlement_ids: set[str] = set()

    for _, row in unified_df.iterrows():
        with StageTimer() as timer:
            result = _check_arithmetic(row, s, used_settlement_ids)

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
            row["confidence_score"] = arithmetic_confidence(result["tolerance_used"])
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


def compute_expected_net(
    order_amount: float,
    refund_amount: float = 0.0,
    mdr_rate: float = MDR_RATE,
    gst_rate: float = GST_ON_MDR_RATE,
) -> tuple[float, float, float]:
    """
    Compute expected net settlement amount.

    Returns:
        (expected_net, mdr_fee, gst_on_mdr)
    """
    mdr_fee = round(order_amount * mdr_rate, 2)
    gst_on_mdr = round(mdr_fee * gst_rate, 2)
    expected_net = round(order_amount - mdr_fee - gst_on_mdr - refund_amount, 2)
    return expected_net, mdr_fee, gst_on_mdr


def _check_arithmetic(
    row: pd.Series,
    settlements_df: pd.DataFrame,
    used_settlement_ids: set[str],
) -> dict:
    """
    Try to find a settlement where the net amount balances arithmetically
    with this order's expected net.
    """
    order_id = row.get("order_id", "UNKNOWN")
    order_amount = row.get("order_amount")
    refund_amount = row.get("total_refund_amount", 0.0) or 0.0

    if pd.isna(order_amount):
        return {
            "matched": False,
            "reason": f"Order {order_id} has no amount — cannot perform arithmetic check.",
        }

    expected_net, mdr_fee, gst_on_mdr = compute_expected_net(order_amount, refund_amount)

    available = settlements_df[
        ~settlements_df["settlement_id"].isin(used_settlement_ids)
    ].copy()

    if available.empty:
        return {"matched": False, "reason": "No settlements available for arithmetic check."}

    # Filter by net_amount proximity
    available["net_diff"] = (available["net_amount"] - expected_net).abs()
    candidates = available[available["net_diff"] <= AMOUNT_TOLERANCE_INR]

    if candidates.empty:
        # Report the nearest candidate for audit trail context
        nearest = available.nsmallest(1, "net_diff").iloc[0]
        diff = round(nearest["net_diff"], 2)
        return {
            "matched": False,
            "reason": (
                f"Arithmetic check failed for order {order_id}. "
                f"Expected net ₹{expected_net:.2f} "
                f"(order ₹{order_amount:.2f} − MDR ₹{mdr_fee:.2f} − GST ₹{gst_on_mdr:.2f} − refund ₹{refund_amount:.2f}). "
                f"Nearest settlement ({nearest['settlement_id']}) net ₹{nearest['net_amount']:.2f} "
                f"differs by ₹{diff:.2f} (exceeds tolerance ₹{AMOUNT_TOLERANCE_INR})."
            ),
        }

    # Pick the closest match
    best = candidates.nsmallest(1, "net_diff").iloc[0]
    tolerance_used = float(best["net_diff"])

    return {
        "matched": True,
        "reason": (
            f"Arithmetic match — order {order_id} ↔ settlement {best['settlement_id']}. "
            f"Expected net ₹{expected_net:.2f}, actual net ₹{best['net_amount']:.2f}, "
            f"diff ₹{tolerance_used:.2f} within tolerance ₹{AMOUNT_TOLERANCE_INR}."
        ),
        "settlement_id": str(best["settlement_id"]),
        "tolerance_used": tolerance_used,
        "expected_net": expected_net,
        "settlement_data": best.to_dict(),
    }


def _empty_frame(reference_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=reference_df.columns)
