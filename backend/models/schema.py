"""
schema.py — SQLAlchemy ORM models for FinPilot.

Defines all database tables as Python classes.
Tables mirror the TRD Section 6 schema exactly.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    order_amount = Column(Float)
    order_date = Column(String)
    customer_id = Column(String)
    status = Column(String)
    gateway = Column(String)
    merchant_ref = Column(String, nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String, primary_key=True)
    order_id = Column(String)
    gateway = Column(String)
    amount = Column(Float)
    payment_date = Column(String)
    status = Column(String)
    narration = Column(String, nullable=True)


class Settlement(Base):
    __tablename__ = "settlements"

    settlement_id = Column(String, primary_key=True)
    payment_id = Column(String, nullable=True)
    order_id = Column(String, nullable=True)
    gateway = Column(String)
    settlement_date = Column(String)
    gross_amount = Column(Float)
    net_amount = Column(Float)
    mdr_fee = Column(Float)
    gst_on_fee = Column(Float)
    refund_amount = Column(Float, default=0.0)


class Refund(Base):
    __tablename__ = "refunds"

    refund_id = Column(String, primary_key=True)
    order_id = Column(String)
    payment_id = Column(String, nullable=True)
    amount = Column(Float)
    refund_date = Column(String)
    status = Column(String, nullable=True)


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    record_id = Column(String, primary_key=True)
    order_id = Column(String)
    match_stage = Column(String)        # exact | attribute | fuzzy | arithmetic | ai | unresolved
    confidence_score = Column(Float, nullable=True)
    confidence_tier = Column(String, nullable=True)
    resolved_amount = Column(Float, nullable=True)
    status = Column(String)             # RESOLVED | EXCEPTION
    ai_explanation = Column(Text, nullable=True)
    ai_candidates = Column(Text, nullable=True)     # JSON string
    silent_failure = Column(Boolean, default=False)
    created_at = Column(String)
    human_review_status = Column(String, nullable=True)  # null | resolved_manual | escalated
    human_review_at = Column(String, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(String)
    stage = Column(String)
    reasoning = Column(Text)
    candidates_considered = Column(Text, nullable=True)   # JSON array string
    ai_explanation = Column(Text, nullable=True)
    timestamp = Column(String)
    duration_ms = Column(Float, nullable=True)
