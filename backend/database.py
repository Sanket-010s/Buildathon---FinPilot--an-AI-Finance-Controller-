"""
database.py — SQLite connection, session management, and persistence for FinPilot.

Responsibilities:
  - Create the SQLite DB and all tables on first run.
  - Provide a session factory for FastAPI routes.
  - Persist PipelineResult (reconciliation results + audit log) to the DB.
  - Provide query helpers used by the API routes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import DB_PATH
from backend.engine.pipeline import PipelineResult
from backend.models.schema import (
    AuditLog,
    Base,
    Order,
    Payment,
    ReconciliationResult,
    Refund,
    Settlement,
)

# ── Engine & session factory ──────────────────────────────────────────────────

_db_url = f"sqlite:///{DB_PATH}"
engine = create_engine(_db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a DB session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Source data persistence ───────────────────────────────────────────────────

def persist_source_data(
    orders_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
    refunds_df: pd.DataFrame,
    db: Session,
) -> None:
    """
    Upsert raw source records into the DB so /records/{id}/audit can
    reference full raw data. Clears existing source data first so
    switching datasets always reflects the new data.
    """
    db.execute(text("DELETE FROM orders"))
    db.execute(text("DELETE FROM payments"))
    db.execute(text("DELETE FROM settlements"))
    db.execute(text("DELETE FROM refunds"))
    db.commit()
    # Orders
    for _, row in orders_df.iterrows():
        db.merge(Order(
            order_id=str(row.get("order_id", "")),
            order_amount=_float(row.get("order_amount")),
            order_date=_str_date(row.get("order_date")),
            customer_id=str(row.get("customer_id", "")),
            status=str(row.get("order_status", row.get("status", ""))),
            gateway=str(row.get("gateway", "")),
            merchant_ref=str(row.get("merchant_ref", "")) or None,
        ))

    # Payments
    for _, row in payments_df.iterrows():
        db.merge(Payment(
            payment_id=str(row.get("payment_id", "")),
            order_id=str(row.get("order_id", "")),
            gateway=str(row.get("gateway", "")),
            amount=_float(row.get("payment_amount", row.get("amount"))),
            payment_date=_str_date(row.get("payment_date")),
            status=str(row.get("payment_status", row.get("status", ""))),
            narration=str(row.get("narration", "")) or None,
        ))

    # Settlements
    for _, row in settlements_df.iterrows():
        db.merge(Settlement(
            settlement_id=str(row.get("settlement_id", "")),
            payment_id=str(row.get("payment_id", "")) or None,
            order_id=str(row.get("order_id", "")) or None,
            gateway=str(row.get("gateway", "")),
            settlement_date=_str_date(row.get("settlement_date")),
            gross_amount=_float(row.get("gross_amount", 0)),
            net_amount=_float(row.get("net_amount", 0)),
            mdr_fee=_float(row.get("mdr_fee", 0)),
            gst_on_fee=_float(row.get("gst_on_fee", 0)),
            refund_amount=_float(row.get("refund_amount", 0)),
        ))

    # Refunds
    for _, row in refunds_df.iterrows():
        db.merge(Refund(
            refund_id=str(row.get("refund_id", "")),
            order_id=str(row.get("order_id", "")),
            payment_id=str(row.get("payment_id", "")) or None,
            amount=_float(row.get("refund_amount", 0)),
            refund_date=_str_date(row.get("refund_date")),
            status=str(row.get("refund_status", "")) or None,
        ))

    db.commit()


# ── Pipeline result persistence ───────────────────────────────────────────────

def persist_pipeline_result(result: PipelineResult, db: Session) -> None:
    """
    Save all reconciliation results and audit log entries to the DB.
    Clears existing results before inserting (each run is a full refresh).
    """
    now = datetime.now(timezone.utc).isoformat()

    # Clear previous results
    db.execute(text("DELETE FROM reconciliation_results"))
    db.execute(text("DELETE FROM audit_log"))
    db.commit()

    # Persist resolved records
    _persist_resolved_df(result.resolved_exact, "exact", "RESOLVED", now, db)
    _persist_resolved_df(result.resolved_attribute, "attribute", "RESOLVED", now, db)
    _persist_resolved_df(result.resolved_fuzzy, "fuzzy", "RESOLVED", now, db)
    _persist_resolved_df(result.resolved_arithmetic, "arithmetic", "RESOLVED", now, db)

    # Persist AI-explained exceptions
    _persist_resolved_df(result.ai_explained, "ai", "EXCEPTION", now, db)

    # Persist unknown exceptions
    _persist_resolved_df(result.exceptions, "unresolved", "EXCEPTION", now, db)

    # Persist audit log
    for entry in result.audit_entries:
        db.add(AuditLog(
            record_id=entry.get("record_id", ""),
            stage=entry.get("stage", ""),
            reasoning=entry.get("reasoning", ""),
            candidates_considered=entry.get("candidates_considered", "[]"),
            ai_explanation=entry.get("ai_explanation"),
            timestamp=entry.get("timestamp", now),
            duration_ms=entry.get("duration_ms"),
        ))

    db.commit()


def _persist_resolved_df(
    df: pd.DataFrame,
    stage: str,
    status: str,
    now: str,
    db: Session,
) -> None:
    if df.empty:
        return
    for _, row in df.iterrows():
        record_id = str(row.get("record_id", row.get("order_id", "")))
        if not record_id:
            continue
        db.merge(ReconciliationResult(
            record_id=record_id,
            order_id=str(row.get("order_id", "")),
            match_stage=str(row.get("match_stage", stage)),
            confidence_score=_float_or_none(row.get("confidence_score")),
            confidence_tier=str(row.get("confidence_tier", "")) or None,
            resolved_amount=_float_or_none(row.get("order_amount")),
            status=str(row.get("match_status", status)),
            ai_explanation=str(row.get("ai_explanation", "")) or None,
            ai_candidates=str(row.get("ai_candidates", "[]")) or None,
            silent_failure=bool(row.get("silent_failure", False)),
            created_at=now,
            human_review_status=None,
            human_review_at=None,
        ))


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_summary(db: Session) -> dict:
    """Aggregate stats for /reconcile/summary."""
    rows = db.execute(text(
        "SELECT match_stage, status, COUNT(*) as cnt, "
        "SUM(resolved_amount) as total_amount, "
        "SUM(silent_failure) as silent_count "
        "FROM reconciliation_results GROUP BY match_stage, status"
    )).fetchall()

    by_stage = {
        "exact": 0, "attribute": 0, "fuzzy": 0,
        "arithmetic": 0, "ai_explained": 0, "unresolved": 0,
    }
    total_resolved = 0
    total_exceptions = 0
    total_amount = 0.0
    silent_failures = 0

    for r in rows:
        stage, status, cnt, amt, silent = r
        amt = amt or 0.0
        silent = silent or 0
        if stage == "ai":
            by_stage["ai_explained"] += cnt
        elif stage in by_stage:
            by_stage[stage] += cnt
        if status == "RESOLVED":
            total_resolved += cnt
            total_amount += amt
        else:
            total_exceptions += cnt
        silent_failures += silent

    # Total refunds
    refund_row = db.execute(text("SELECT COALESCE(SUM(amount), 0) FROM refunds")).fetchone()
    total_refunds = float(refund_row[0]) if refund_row else 0.0

    # Duration from most recent run (stored in audit_log timestamps)
    dur_row = db.execute(text(
        "SELECT MIN(timestamp), MAX(timestamp) FROM audit_log"
    )).fetchone()
    duration_seconds = 0.0

    total = total_resolved + total_exceptions
    match_rate = round(total_resolved / total, 4) if total > 0 else 0.0

    return {
        "total_records": total,
        "resolved": total_resolved,
        "exceptions": total_exceptions,
        "match_rate": match_rate,
        "duration_seconds": duration_seconds,
        "by_stage": by_stage,
        "total_settled_amount": round(total_amount, 2),
        "total_refunds": round(total_refunds, 2),
        "silent_failures": silent_failures,
    }


def get_all_records(db: Session) -> list[dict]:
    """All reconciliation records for the overview table."""
    rows = db.execute(text(
        "SELECT record_id, order_id, resolved_amount, created_at, "
        "match_stage, status, ai_explanation, human_review_status "
        "FROM reconciliation_results ORDER BY created_at DESC"
    )).fetchall()

    results = []
    for r in rows:
        record_id, order_id, amount, created_at, stage, status, ai_exp, hr_status = r
        order_row = db.execute(text(
            "SELECT order_date FROM orders WHERE order_id = :oid"
        ), {"oid": order_id}).fetchone()
        results.append({
            "record_id": record_id,
            "order_id": order_id,
            "order_amount": amount,
            "order_date": order_row[0] if order_row else None,
            "match_stage": stage,
            "status": status,
            "ai_explanation": ai_exp,
            "human_review_status": hr_status,
        })
    return results


def get_exceptions(db: Session) -> list[dict]:
    """All exception records for /exceptions."""
    rows = db.execute(text(
        "SELECT record_id, order_id, resolved_amount, created_at, "
        "match_stage, status, confidence_tier, ai_explanation, human_review_status "
        "FROM reconciliation_results WHERE status = 'EXCEPTION' "
        "ORDER BY created_at DESC"
    )).fetchall()

    results = []
    for r in rows:
        record_id, order_id, amount, created_at, stage, status, tier, ai_exp, hr_status = r
        # Fetch order date and customer from orders table
        order_row = db.execute(text(
            "SELECT order_date, customer_id FROM orders WHERE order_id = :oid"
        ), {"oid": order_id}).fetchone()
        order_date = order_row[0] if order_row else None
        customer_id = order_row[1] if order_row else None

        results.append({
            "record_id": record_id,
            "order_id": order_id,
            "order_amount": amount,
            "order_date": order_date,
            "customer_id": customer_id,
            "stage_reached": stage,
            "status": status,
            "confidence_tier": tier,
            "ai_explanation": ai_exp,
            "human_review_status": hr_status,
        })
    return results


def get_exception_detail(record_id: str, db: Session) -> dict | None:
    """Full detail for one exception record."""
    row = db.execute(text(
        "SELECT * FROM reconciliation_results WHERE record_id = :rid"
    ), {"rid": record_id}).fetchone()

    if not row:
        return None

    # Map columns
    cols = [
        "record_id", "order_id", "match_stage", "confidence_score",
        "confidence_tier", "resolved_amount", "status", "ai_explanation",
        "ai_candidates", "silent_failure", "created_at",
        "human_review_status", "human_review_at",
    ]
    d = dict(zip(cols, row))

    # Fetch order
    o = db.execute(text("SELECT * FROM orders WHERE order_id = :oid"),
                   {"oid": d["order_id"]}).fetchone()
    # Fetch payment
    p = db.execute(text("SELECT * FROM payments WHERE order_id = :oid"),
                   {"oid": d["order_id"]}).fetchone()
    # Fetch settlement
    s = db.execute(text(
        "SELECT * FROM settlements WHERE order_id = :oid OR payment_id = "
        "(SELECT payment_id FROM payments WHERE order_id = :oid LIMIT 1)"
    ), {"oid": d["order_id"]}).fetchone()

    # Audit stages attempted
    audit_rows = db.execute(text(
        "SELECT stage FROM audit_log WHERE record_id = :rid ORDER BY log_id"
    ), {"rid": record_id}).fetchall()
    stages_attempted = [r[0] for r in audit_rows]

    # Parse AI candidates
    candidates = []
    if d.get("ai_candidates"):
        try:
            raw = json.loads(d["ai_candidates"])
            candidates = [
                {"source": c.get("source", ""), "id": c.get("id", ""),
                 "amount": c.get("amount"), "date": c.get("date")}
                for c in raw
            ]
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "record_id": d["record_id"],
        "order_id": d["order_id"],
        "order_amount": o[1] if o else d.get("resolved_amount"),
        "order_date": o[2] if o else None,
        "customer_id": o[3] if o else None,
        "gateway": o[5] if o else None,
        "order_status": o[4] if o else None,
        "payment_id": p[0] if p else None,
        "payment_amount": p[3] if p else None,
        "payment_status": p[5] if p else None,
        "settlement_id": s[0] if s else None,
        "settlement_net": s[5] if s else None,
        "total_refunds": None,
        "silent_failure": bool(d.get("silent_failure", False)),
        "stages_attempted": stages_attempted,
        "final_stage": d["match_stage"],
        "status": d["status"],
        "confidence_score": d.get("confidence_score"),
        "confidence_tier": d.get("confidence_tier"),
        "ai_explanation": d.get("ai_explanation"),
        "candidates_considered": candidates,
        "human_review_status": d.get("human_review_status"),
        "human_review_at": d.get("human_review_at"),
        "created_at": d.get("created_at"),
    }


def get_audit_trail(record_id: str, db: Session) -> list[dict]:
    """Full audit log for one record."""
    rows = db.execute(text(
        "SELECT log_id, record_id, stage, reasoning, candidates_considered, "
        "ai_explanation, timestamp, duration_ms "
        "FROM audit_log WHERE record_id = :rid ORDER BY log_id"
    ), {"rid": record_id}).fetchall()

    entries = []
    for r in rows:
        log_id, rid, stage, reasoning, candidates_json, ai_exp, ts, dur = r
        try:
            candidates = json.loads(candidates_json) if candidates_json else []
        except (json.JSONDecodeError, TypeError):
            candidates = []
        entries.append({
            "log_id": log_id,
            "record_id": rid,
            "stage": stage,
            "reasoning": reasoning,
            "candidates_considered": candidates,
            "ai_explanation": ai_exp,
            "timestamp": ts,
            "duration_ms": dur,
        })
    return entries


def update_human_review(record_id: str, action: str, db: Session) -> dict | None:
    """Update human_review_status for a record."""
    now = datetime.now(timezone.utc).isoformat()
    result = db.execute(text(
        "UPDATE reconciliation_results "
        "SET human_review_status = :action, human_review_at = :now "
        "WHERE record_id = :rid"
    ), {"action": action, "now": now, "rid": record_id})
    db.commit()
    if result.rowcount == 0:
        return None
    return {"record_id": record_id, "human_review_status": action, "human_review_at": now}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(val) -> float | None:
    try:
        f = float(val)
        return f if not (f != f) else None  # NaN check
    except (TypeError, ValueError):
        return None


def _str_date(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val[:10]
    try:
        return str(val)[:10]
    except Exception:
        return None
