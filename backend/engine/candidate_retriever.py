"""
candidate_retriever.py — Finds nearby candidate records for Stage 5 AI explanation.

Searches the full settlements, payments, and refunds DataFrames for records
that are plausibly related to an unresolved order — within a date window
and amount window — to provide the LLM with context.

The LLM uses these candidates to EXPLAIN, not to match.
"""

from __future__ import annotations

import pandas as pd

from backend.config import AI_CANDIDATE_WINDOW_DAYS, AI_CANDIDATE_AMOUNT_PCT, AI_MAX_CANDIDATES


def retrieve_candidates(
    row: pd.Series,
    settlements_df: pd.DataFrame,
    payments_df: pd.DataFrame | None = None,
    refunds_df: pd.DataFrame | None = None,
) -> list[dict]:
    """
    Retrieve top N candidate records near the given unresolved order.

    Args:
        row:             The unresolved record (unified row).
        settlements_df:  Full normalised settlements DataFrame.
        payments_df:     Full normalised payments DataFrame (optional).
        refunds_df:      Full normalised refunds DataFrame (optional).

    Returns:
        List of candidate dicts, each with source, id, amount, date, and notes.
    """
    order_id = str(row.get("order_id", "UNKNOWN"))
    order_amount = row.get("order_amount")
    order_date = pd.to_datetime(row.get("order_date"), errors="coerce")

    candidates: list[dict] = []

    # ── Search settlements ────────────────────────────────────────────────────
    s = settlements_df.copy()
    if "setl_settlement_id" in s.columns:
        s.columns = [c.replace("setl_", "") if c.startswith("setl_") else c for c in s.columns]

    if "settlement_date" in s.columns:
        s["settlement_date"] = pd.to_datetime(s["settlement_date"], errors="coerce")

    s_candidates = _filter_candidates(
        df=s,
        id_col="settlement_id",
        amount_col="net_amount",
        date_col="settlement_date",
        order_amount=order_amount,
        order_date=order_date,
        source="settlement",
    )
    candidates.extend(s_candidates)

    # ── Search payments (if provided) ─────────────────────────────────────────
    if payments_df is not None and not payments_df.empty:
        p = payments_df.copy()
        if "pay_payment_id" in p.columns:
            p.columns = [c.replace("pay_", "") if c.startswith("pay_") else c for c in p.columns]

        if "payment_date" in p.columns:
            p["payment_date"] = pd.to_datetime(p["payment_date"], errors="coerce")

        p_candidates = _filter_candidates(
            df=p,
            id_col="payment_id",
            amount_col="payment_amount",
            date_col="payment_date",
            order_amount=order_amount,
            order_date=order_date,
            source="payment",
        )
        candidates.extend(p_candidates)

    # ── Search refunds (if provided) ──────────────────────────────────────────
    if refunds_df is not None and not refunds_df.empty:
        r = refunds_df.copy()
        if "refund_date" in r.columns:
            r["refund_date"] = pd.to_datetime(r["refund_date"], errors="coerce")

        r_candidates = _filter_candidates(
            df=r,
            id_col="refund_id",
            amount_col="refund_amount",
            date_col="refund_date",
            order_amount=order_amount,
            order_date=order_date,
            source="refund",
        )
        candidates.extend(r_candidates)

    # Sort by relevance score (closer date + closer amount = higher)
    candidates.sort(key=lambda c: c.get("_relevance_score", 0), reverse=True)

    # Return top N without internal scoring field
    top = candidates[:AI_MAX_CANDIDATES]
    for c in top:
        c.pop("_relevance_score", None)

    return top


def _filter_candidates(
    df: pd.DataFrame,
    id_col: str,
    amount_col: str,
    date_col: str,
    order_amount: float | None,
    order_date: pd.Timestamp | None,
    source: str,
) -> list[dict]:
    """Filter a DataFrame for candidate rows and return as list of dicts."""
    if df.empty or id_col not in df.columns:
        return []

    result = df.copy()

    # Date filter
    if order_date and not pd.isna(order_date) and date_col in result.columns:
        date_mask = (
            (result[date_col] - order_date).dt.days.abs() <= AI_CANDIDATE_WINDOW_DAYS
        )
        result = result[date_mask]

    # Amount filter (±AI_CANDIDATE_AMOUNT_PCT of order amount)
    if order_amount and not pd.isna(order_amount) and amount_col in result.columns:
        lower = order_amount * (1 - AI_CANDIDATE_AMOUNT_PCT)
        upper = order_amount * (1 + AI_CANDIDATE_AMOUNT_PCT)
        result = result[(result[amount_col] >= lower) & (result[amount_col] <= upper)]

    candidates = []
    for _, row in result.iterrows():
        cid = str(row.get(id_col, ""))
        amount = row.get(amount_col, None)
        date_val = row.get(date_col, None)

        # Compute relevance: penalise by date diff and amount diff
        date_score = 0.0
        if order_date and date_val and not pd.isna(date_val):
            date_diff = abs((pd.to_datetime(date_val) - order_date).days)
            date_score = max(0, AI_CANDIDATE_WINDOW_DAYS - date_diff)

        amount_score = 0.0
        if order_amount and amount and not pd.isna(amount):
            pct_diff = abs(amount - order_amount) / (order_amount + 1e-9)
            amount_score = max(0, AI_CANDIDATE_AMOUNT_PCT - pct_diff) * 100

        candidates.append({
            "source": source,
            "id": cid,
            "amount": round(float(amount), 2) if amount and not pd.isna(amount) else None,
            "date": str(date_val.date()) if date_val and not pd.isna(date_val) else None,
            "_relevance_score": date_score + amount_score,
        })

    return candidates
