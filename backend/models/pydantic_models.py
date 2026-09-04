"""
pydantic_models.py — Request/response schemas for the FinPilot FastAPI backend.

These are the shapes the API exposes — separate from the SQLAlchemy ORM models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ── /reconcile/run ────────────────────────────────────────────────────────────

class RunResponse(BaseModel):
    status: str
    total_records: int
    resolved: int
    exceptions: int
    match_rate: float
    duration_seconds: float


# ── /reconcile/summary ────────────────────────────────────────────────────────

class StageSummary(BaseModel):
    exact: int
    attribute: int
    fuzzy: int
    arithmetic: int
    ai_explained: int
    unresolved: int


class SummaryResponse(BaseModel):
    total_records: int
    resolved: int
    exceptions: int
    match_rate: float
    duration_seconds: float
    by_stage: StageSummary
    total_settled_amount: float
    total_refunds: float
    silent_failures: int


# ── /exceptions ───────────────────────────────────────────────────────────────

class ExceptionItem(BaseModel):
    record_id: str
    order_id: str | None
    order_amount: float | None
    order_date: str | None
    customer_id: str | None
    stage_reached: str
    status: str
    confidence_tier: str | None
    ai_explanation: str | None
    human_review_status: str | None


# ── /exceptions/{record_id} ───────────────────────────────────────────────────

class CandidateRecord(BaseModel):
    source: str
    id: str
    amount: float | None
    date: str | None


class ExceptionDetail(BaseModel):
    record_id: str
    order_id: str | None
    order_amount: float | None
    order_date: str | None
    customer_id: str | None
    gateway: str | None
    order_status: str | None
    payment_id: str | None
    payment_amount: float | None
    payment_status: str | None
    settlement_id: str | None
    settlement_net: float | None
    total_refunds: float | None
    silent_failure: bool
    stages_attempted: list[str]
    final_stage: str
    status: str
    confidence_score: float | None
    confidence_tier: str | None
    ai_explanation: str | None
    candidates_considered: list[CandidateRecord]
    human_review_status: str | None
    human_review_at: str | None
    created_at: str | None


# ── /records/{record_id}/audit ────────────────────────────────────────────────

class AuditEntry(BaseModel):
    log_id: int
    record_id: str
    stage: str
    reasoning: str
    candidates_considered: list[str]
    ai_explanation: str | None
    timestamp: str
    duration_ms: float | None


class AuditTrailResponse(BaseModel):
    record_id: str
    entries: list[AuditEntry]


# ── Human review action ───────────────────────────────────────────────────────

class ReviewAction(BaseModel):
    action: str   # "resolved_manual" | "escalated"


class ReviewResponse(BaseModel):
    record_id: str
    human_review_status: str
    human_review_at: str
    message: str
