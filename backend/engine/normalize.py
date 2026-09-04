"""
normalize.py — Data normalization layer for FinPilot.

Unifies raw CSV data (from multiple simulated gateway formats) into one
internal schema so the reconciliation pipeline works against a single,
consistent structure.

Public API:
    load_and_normalize(data_dir) -> (orders_df, payments_df, settlements_df, refunds_df)
    unify(orders_df, payments_df, settlements_df, refunds_df) -> unified_df

The 'unified_df' is the primary input to the reconciliation pipeline —
one row per order, with its associated payment, settlement, and refund
data flattened alongside it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Column name normalisation maps ────────────────────────────────────────────
# Different gateways use different names for the same concept.
# We map everything to a canonical internal name.

ORDER_COLUMNS = {
    # raw name          → canonical name
    "order_id":          "order_id",
    "order_amount":      "order_amount",
    "amount":            "order_amount",
    "order_date":        "order_date",
    "date":              "order_date",
    "customer_id":       "customer_id",
    "cust_id":           "customer_id",
    "customer":          "customer_id",
    "status":            "order_status",
    "gateway":           "gateway",
    "merchant_ref":      "merchant_ref",
    "amount_reported":   "amount_reported",
}

PAYMENT_COLUMNS = {
    "payment_id":        "payment_id",
    "txn_id":            "payment_id",
    "transaction_id":    "payment_id",
    "order_id":          "order_id",
    "gateway":           "gateway",
    "amount":            "payment_amount",
    "paid_amount":       "payment_amount",
    "payment_date":      "payment_date",
    "txn_date":          "payment_date",
    "status":            "payment_status",
    "narration":         "narration",
}

SETTLEMENT_COLUMNS = {
    "settlement_id":     "settlement_id",
    "setl_id":           "settlement_id",
    "payment_id":        "payment_id",
    "order_id":          "order_id",
    "gateway":           "gateway",
    "settlement_date":   "settlement_date",
    "setl_date":         "settlement_date",
    "gross_amount":      "gross_amount",
    "net_amount":        "net_amount",
    "settled_amount":    "net_amount",
    "mdr_fee":           "mdr_fee",
    "fee":               "mdr_fee",
    "gst_on_fee":        "gst_on_fee",
    "tax":               "gst_on_fee",
    "refund_amount":     "refund_amount",
    "narration":         "settlement_narration",
}

REFUND_COLUMNS = {
    "refund_id":         "refund_id",
    "order_id":          "order_id",
    "payment_id":        "payment_id",
    "amount":            "refund_amount",
    "refund_amount":     "refund_amount",
    "refund_date":       "refund_date",
    "date":              "refund_date",
    "status":            "refund_status",
}


def _rename(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Rename columns present in df according to col_map, ignore unknown columns."""
    rename_dict = {k: v for k, v in col_map.items() if k in df.columns}
    return df.rename(columns=rename_dict)


def _parse_dates(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """Parse date columns to datetime, coerce errors to NaT."""
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _fill_missing(df: pd.DataFrame, columns: list[str], fill_value=None) -> pd.DataFrame:
    """Ensure expected columns exist, filling with fill_value if absent."""
    for col in columns:
        if col not in df.columns:
            df[col] = fill_value
    return df


# ── Per-source normalisation ──────────────────────────────────────────────────

def normalize_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename(df, ORDER_COLUMNS)
    df = _parse_dates(df, ["order_date"])
    df = _fill_missing(df, [
        "order_id", "order_amount", "order_date",
        "customer_id", "order_status", "gateway",
        "merchant_ref", "amount_reported",
    ])
    df["order_amount"] = pd.to_numeric(df["order_amount"], errors="coerce")
    df["order_status"] = df["order_status"].str.lower().str.strip()
    # Detect silent failures: order status is 'failed' but we keep them visible
    df["is_silent_failure_candidate"] = df["order_status"] == "failed"
    return df


def normalize_payments(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename(df, PAYMENT_COLUMNS)
    df = _parse_dates(df, ["payment_date"])
    df = _fill_missing(df, [
        "payment_id", "order_id", "gateway",
        "payment_amount", "payment_date", "payment_status", "narration",
    ])
    df["payment_amount"] = pd.to_numeric(df["payment_amount"], errors="coerce")
    df["payment_status"] = df["payment_status"].str.lower().str.strip()
    return df


def normalize_settlements(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename(df, SETTLEMENT_COLUMNS)
    df = _parse_dates(df, ["settlement_date"])
    df = _fill_missing(df, [
        "settlement_id", "payment_id", "order_id", "gateway",
        "settlement_date", "gross_amount", "net_amount",
        "mdr_fee", "gst_on_fee", "refund_amount", "settlement_narration",
    ])
    for col in ["gross_amount", "net_amount", "mdr_fee", "gst_on_fee", "refund_amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def normalize_refunds(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename(df, REFUND_COLUMNS)
    df = _parse_dates(df, ["refund_date"])
    df = _fill_missing(df, [
        "refund_id", "order_id", "payment_id",
        "refund_amount", "refund_date", "refund_status",
    ])
    df["refund_amount"] = pd.to_numeric(df["refund_amount"], errors="coerce").fillna(0.0)
    return df


# ── Unified record builder ────────────────────────────────────────────────────

def unify(
    orders_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
    refunds_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build a unified DataFrame: one row per order, with best-effort joins
    to payment, settlement, and refund data.

    Columns in the result (prefixed by source):
        order_*  — from orders
        pay_*    — from best-matched payment
        setl_*   — from best-matched settlement
        refund_* — from best-matched refund (or 0 if none)

    Records with no linked payment or settlement are still included —
    they will surface as exceptions in the pipeline.
    """
    # Normalise inputs
    o = normalize_orders(orders_df.copy())
    p = normalize_payments(payments_df.copy())
    s = normalize_settlements(settlements_df.copy())
    r = normalize_refunds(refunds_df.copy())

    # Aggregate refunds per order (sum refund amounts)
    refund_agg = (
        r.groupby("order_id", dropna=True)
        .agg(total_refund_amount=("refund_amount", "sum"),
             refund_ids=("refund_id", lambda x: list(x)),
             latest_refund_date=("refund_date", "max"))
        .reset_index()
    )

    # Join orders ← payments (on order_id)
    unified = o.merge(
        p.add_prefix("pay_").rename(columns={"pay_order_id": "order_id"}),
        on="order_id",
        how="left",
    )

    # Join ← settlements via payment_id (primary) then order_id (fallback)
    s_via_payment = (
        s[s["payment_id"].notna()]
        .add_prefix("setl_")
        .rename(columns={"setl_payment_id": "pay_payment_id"})
    )
    s_via_order = (
        s[s["order_id"].notna() & s["payment_id"].isna()]
        .add_prefix("setl_")
        .rename(columns={"setl_order_id": "order_id"})
    )

    unified = unified.merge(s_via_payment, on="pay_payment_id", how="left")

    # For rows still missing settlement, try joining by order_id
    no_setl_mask = unified["setl_settlement_id"].isna()
    if no_setl_mask.any():
        filled = unified[no_setl_mask].drop(
            columns=[c for c in unified.columns if c.startswith("setl_")],
            errors="ignore"
        ).merge(s_via_order, on="order_id", how="left")
        unified = pd.concat([unified[~no_setl_mask], filled], ignore_index=True)

    # Join ← refunds (aggregated)
    unified = unified.merge(refund_agg, on="order_id", how="left")
    unified["total_refund_amount"] = unified["total_refund_amount"].fillna(0.0)
    unified["refund_ids"] = unified["refund_ids"].apply(
        lambda x: x if isinstance(x, list) else []
    )

    # Add a record_id for pipeline tracking
    unified.insert(0, "record_id", unified["order_id"])

    # Add a flag for silent failures:
    # order says 'failed' but payment was captured → genuine silent failure
    if "pay_payment_status" in unified.columns:
        unified["silent_failure"] = (
            unified["is_silent_failure_candidate"].fillna(False) &
            (unified["pay_payment_status"] == "captured")
        )
    else:
        unified["silent_failure"] = False

    return unified


# ── Loader ────────────────────────────────────────────────────────────────────

def load_and_normalize(data_dir: str | Path = DATA_DIR):
    """
    Load the four CSV files from data_dir and return normalised DataFrames.
    Raises FileNotFoundError if any CSV is missing.
    """
    data_dir = Path(data_dir)
    required = ["orders.csv", "payments.csv", "settlements.csv", "refunds.csv"]
    for fname in required:
        if not (data_dir / fname).exists():
            raise FileNotFoundError(
                f"Missing {fname} in {data_dir}. "
                "Run: python data/synthetic_generator.py first."
            )

    orders_df = pd.read_csv(data_dir / "orders.csv")
    payments_df = pd.read_csv(data_dir / "payments.csv")
    settlements_df = pd.read_csv(data_dir / "settlements.csv")
    refunds_df = pd.read_csv(data_dir / "refunds.csv")

    return (
        normalize_orders(orders_df),
        normalize_payments(payments_df),
        normalize_settlements(settlements_df),
        normalize_refunds(refunds_df),
    )
