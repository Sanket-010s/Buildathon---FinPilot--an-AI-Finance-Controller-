"""
synthetic_generator.py — Generates realistic synthetic financial data for FinPilot.

Produces four CSV files in the same /data directory:
  - orders.csv
  - payments.csv
  - settlements.csv
  - refunds.csv

Design intent:
  - 200+ order records across multiple simulated gateway formats.
  - Intentional mismatches and anomalies so all 5 reconciliation stages get exercised:
      * ~70% exact-matchable (clean IDs align)
      * ~10% attribute-matchable (slight date/amount drift)
      * ~5%  fuzzy-matchable (reference string variations)
      * ~5%  arithmetic-verifiable (no direct link but maths balances)
      * ~5%  AI-explained (plausible but not deterministically resolvable)
      * ~5%  genuine exceptions (unknown, nothing matches)
  - Two simulated gateway formats (Razorpay-style, PayU-style) with differing column names.
  - Silent payment failure injection (~1.8% of orders).

Usage:
  python data/synthetic_generator.py              # generates 220 records
  python data/synthetic_generator.py --records 300
"""

import argparse
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ── Reproducibility ──────────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent
GATEWAYS = ["razorpay", "payu", "cashfree"]
CUSTOMER_POOL_SIZE = 60
BASE_DATE = datetime(2024, 1, 1)
DATE_SPAN_DAYS = 180  # 6 months of data

MDR_RATE = 0.02        # 2%
GST_RATE = 0.18        # 18% on MDR

# Anomaly rates (fractions of total orders)
RATE_EXACT = 0.70
RATE_ATTRIBUTE = 0.10
RATE_FUZZY = 0.05
RATE_ARITHMETIC = 0.05
RATE_AI = 0.05
RATE_EXCEPTION = 0.05   # truly unresolvable


def random_date(base: datetime = BASE_DATE, span: int = DATE_SPAN_DAYS) -> datetime:
    return base + timedelta(days=random.randint(0, span))


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def round2(val: float) -> float:
    return round(val, 2)


def gen_customer_pool(size: int) -> list[str]:
    return [f"CUST-{str(i).zfill(4)}" for i in range(1, size + 1)]


def gen_order_id(index: int) -> str:
    return f"ORD-{str(index).zfill(4)}"


def gen_payment_id(gateway: str, index: int) -> str:
    prefix = {"razorpay": "pay", "payu": "pyu", "cashfree": "cf"}
    return f"{prefix.get(gateway, 'pay')}_{str(index).zfill(6)}"


def gen_settlement_id(gateway: str, index: int) -> str:
    return f"SETL-{gateway[:3].upper()}-{str(index).zfill(4)}"


def gen_refund_id(index: int) -> str:
    return f"RFD-{str(index).zfill(4)}"


def compute_net(amount: float, refund: float = 0.0) -> float:
    mdr = round2(amount * MDR_RATE)
    gst = round2(mdr * GST_RATE)
    return round2(amount - mdr - gst - refund)


# ── Generators per anomaly type ───────────────────────────────────────────────

def make_exact(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Clean record — IDs match exactly across all sources."""
    oid = gen_order_id(idx)
    pid = gen_payment_id(gateway, idx)
    sid = gen_settlement_id(gateway, idx)
    amount = round2(random.uniform(200, 9999))
    odate = random_date()
    pdate = odate + timedelta(days=random.randint(0, 1))
    sdate = pdate + timedelta(days=random.randint(1, 3))

    has_refund = random.random() < 0.12
    refund_amount = round2(amount * random.uniform(0.1, 1.0)) if has_refund else 0.0

    order = {"order_id": oid, "order_amount": amount, "order_date": fmt_date(odate),
             "customer_id": customer, "status": "paid", "gateway": gateway}
    payment = {"payment_id": pid, "order_id": oid, "gateway": gateway,
               "amount": amount, "payment_date": fmt_date(pdate), "status": "captured"}
    net = compute_net(amount, refund_amount)
    settlement = {"settlement_id": sid, "payment_id": pid, "order_id": oid, "gateway": gateway,
                  "settlement_date": fmt_date(sdate), "gross_amount": amount,
                  "net_amount": net, "mdr_fee": round2(amount * MDR_RATE),
                  "gst_on_fee": round2(amount * MDR_RATE * GST_RATE),
                  "refund_amount": refund_amount}
    refund = None
    if has_refund:
        rdate = odate + timedelta(days=random.randint(2, 10))
        refund = {"refund_id": gen_refund_id(idx), "order_id": oid, "payment_id": pid,
                  "amount": refund_amount, "refund_date": fmt_date(rdate), "status": "processed"}
    return order, payment, settlement, refund


def make_attribute(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Date drifted by 2–5 days (IDs still link but date tolerance needed)."""
    order, payment, settlement, refund = make_exact(idx, customer, gateway)
    drift = random.randint(2, 5)
    pay_date = datetime.strptime(payment["payment_date"], "%Y-%m-%d")
    payment["payment_date"] = fmt_date(pay_date + timedelta(days=drift))
    # Slightly perturb amount within ±10 to simulate rounding/FX
    order["amount_reported"] = round2(order["order_amount"] + random.uniform(-5, 5))
    return order, payment, settlement, refund


def make_fuzzy(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Reference string has a typo / format difference."""
    order, payment, settlement, refund = make_exact(idx, customer, gateway)
    # Simulate a merchant reference note with slight variation
    base_ref = f"INV{idx:04d}"
    order["merchant_ref"] = base_ref
    # Payment has a slightly different narration (typo, extra space, etc.)
    variations = [
        base_ref.replace("INV", "Inv"),
        base_ref + " ",
        f"INV-{idx:04d}",
        base_ref[:3] + base_ref[4:],  # drop one char
    ]
    payment["narration"] = random.choice(variations)
    settlement["narration"] = order["merchant_ref"]
    return order, payment, settlement, refund


def make_arithmetic(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """No direct ID link between order and settlement — but arithmetic balances."""
    order, payment, settlement, refund = make_exact(idx, customer, gateway)
    # Sever the order_id link in settlement to simulate a lump-sum settlement
    settlement["order_id"] = None
    settlement["payment_id"] = None
    # Keep the net amount correct so arithmetic check resolves it
    return order, payment, settlement, refund


def make_ai(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Date drift + amount difference that escapes deterministic stages."""
    order, payment, settlement, refund = make_exact(idx, customer, gateway)
    # Large date drift (exceeds tolerance)
    pay_date = datetime.strptime(payment["payment_date"], "%Y-%m-%d")
    payment["payment_date"] = fmt_date(pay_date + timedelta(days=random.randint(5, 10)))
    # Amount off by more than ₹1 (breaks arithmetic check too)
    settlement["net_amount"] = round2(settlement["net_amount"] + random.uniform(45, 100))
    # Sever direct IDs
    settlement["order_id"] = None
    settlement["payment_id"] = None
    return order, payment, settlement, refund


def make_exception(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Completely orphaned order — no matching payment or settlement."""
    oid = gen_order_id(idx)
    amount = round2(random.uniform(200, 9999))
    odate = random_date()
    order = {"order_id": oid, "order_amount": amount, "order_date": fmt_date(odate),
             "customer_id": customer, "status": "paid", "gateway": gateway}
    # Payment exists but references a wrong/unknown order ID
    pid = gen_payment_id(gateway, idx)
    wrong_oid = f"ORD-{str(idx + 5000).zfill(4)}"   # ID that doesn't exist
    payment = {"payment_id": pid, "order_id": wrong_oid, "gateway": gateway,
               "amount": amount + random.uniform(100, 500),
               "payment_date": fmt_date(odate + timedelta(days=random.randint(6, 15))),
               "status": "captured"}
    # Settlement is totally unrelated
    sid = gen_settlement_id(gateway, idx + 1000)
    settlement = {"settlement_id": sid, "payment_id": None, "order_id": None, "gateway": gateway,
                  "settlement_date": fmt_date(odate + timedelta(days=20)),
                  "gross_amount": round2(amount * 3.5),
                  "net_amount": round2(amount * 3.4),
                  "mdr_fee": round2(amount * 3.5 * MDR_RATE),
                  "gst_on_fee": round2(amount * 3.5 * MDR_RATE * GST_RATE),
                  "refund_amount": 0.0}
    return order, payment, settlement, None


def make_silent_failure(idx: int, customer: str, gateway: str) -> tuple[dict, dict, dict, dict | None]:
    """Order marked 'failed' in merchant system but payment was actually captured."""
    order, payment, settlement, refund = make_exact(idx, customer, gateway)
    order["status"] = "failed"   # merchant thinks it failed
    payment["status"] = "captured"  # but gateway captured it — silent failure
    return order, payment, settlement, refund


# ── Main generator ─────────────────────────────────────────────────────────────

def generate(n_records: int = 220) -> None:
    customers = gen_customer_pool(CUSTOMER_POOL_SIZE)

    # Compute counts per category
    n_exact = int(n_records * RATE_EXACT)
    n_attr = int(n_records * RATE_ATTRIBUTE)
    n_fuzzy = int(n_records * RATE_FUZZY)
    n_arith = int(n_records * RATE_ARITHMETIC)
    n_ai = int(n_records * RATE_AI)
    n_exc = n_records - n_exact - n_attr - n_fuzzy - n_arith - n_ai  # remainder
    n_silent = max(int(n_records * 0.018), 1)  # ~1.8% silent failures

    print(f"Generating {n_records} synthetic records:")
    print(f"  Exact-matchable:   {n_exact}")
    print(f"  Attribute-match:   {n_attr}")
    print(f"  Fuzzy-match:       {n_fuzzy}")
    print(f"  Arithmetic-verify: {n_arith}")
    print(f"  AI-explained:      {n_ai}")
    print(f"  True exceptions:   {n_exc}")
    print(f"  Silent failures:   {n_silent} (overlap with above)")

    orders_rows, payments_rows, settlements_rows, refunds_rows = [], [], [], []

    idx = 1

    def add(o, p, s, r):
        orders_rows.append(o)
        payments_rows.append(p)
        settlements_rows.append(s)
        if r:
            refunds_rows.append(r)

    makers = (
        [(make_exact, n_exact)] +
        [(make_attribute, n_attr)] +
        [(make_fuzzy, n_fuzzy)] +
        [(make_arithmetic, n_arith)] +
        [(make_ai, n_ai)] +
        [(make_exception, n_exc)]
    )

    for maker_fn, count in makers:
        for _ in range(count):
            gw = random.choice(GATEWAYS)
            cust = random.choice(customers)
            o, p, s, r = maker_fn(idx, cust, gw)
            add(o, p, s, r)
            idx += 1

    # Sprinkle silent failures over exact-match records
    silent_candidates = [o for o in orders_rows if o.get("status") == "paid"]
    for o in random.sample(silent_candidates, min(n_silent, len(silent_candidates))):
        o["status"] = "failed"  # mark as failed in orders while payment stays captured

    # Build DataFrames
    orders_df = pd.DataFrame(orders_rows)
    payments_df = pd.DataFrame(payments_rows)
    settlements_df = pd.DataFrame(settlements_rows)
    refunds_df = pd.DataFrame(refunds_rows)

    # Ensure consistent columns
    for col in ["merchant_ref", "amount_reported"]:
        if col not in orders_df.columns:
            orders_df[col] = None
    for col in ["narration"]:
        if col not in payments_df.columns:
            payments_df[col] = None
        if col not in settlements_df.columns:
            settlements_df[col] = None

    # Save to CSV
    orders_df.to_csv(DATA_DIR / "orders.csv", index=False)
    payments_df.to_csv(DATA_DIR / "payments.csv", index=False)
    settlements_df.to_csv(DATA_DIR / "settlements.csv", index=False)
    refunds_df.to_csv(DATA_DIR / "refunds.csv", index=False)

    print(f"\nSaved to {DATA_DIR}:")
    print(f"  orders.csv       — {len(orders_df)} rows")
    print(f"  payments.csv     — {len(payments_df)} rows")
    print(f"  settlements.csv  — {len(settlements_df)} rows")
    print(f"  refunds.csv      — {len(refunds_df)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinPilot synthetic data generator")
    parser.add_argument("--records", type=int, default=220, help="Number of order records to generate")
    args = parser.parse_args()
    generate(args.records)
