"""
confidence.py — Deterministic confidence scoring rules for FinPilot.

This is the single source of truth for all confidence scores.
The LLM has NO access to modify or assign these scores.

Confidence rules per stage (from TRD Section 6):
    Exact      : 1.00 (no deduction)
    Attribute  : 0.90 base, −0.02 per day of date drift tolerated
    Fuzzy      : (similarity / 100) × 0.85, rejected below threshold
    Arithmetic : 0.95 base, −0.05 if full tolerance band used
    AI-explained: no numeric score — returns None with tier label
"""

from __future__ import annotations

from backend.config import DATE_TOLERANCE_DAYS, AMOUNT_TOLERANCE_INR, FUZZY_THRESHOLD


def exact_confidence() -> float:
    """Stage 1: perfect ID match — always 1.0."""
    return 1.0


def attribute_confidence(date_drift_days: int = 0) -> float:
    """
    Stage 2: attribute match.
    Base 0.90, deduct 0.02 per day of date drift tolerated.
    Minimum clamped at 0.70 to avoid negative/misleading scores.
    """
    base = 0.90
    deduction = min(date_drift_days, DATE_TOLERANCE_DAYS) * 0.02
    return round(max(base - deduction, 0.70), 4)


def fuzzy_confidence(similarity_score: float) -> float | None:
    """
    Stage 3: fuzzy match.
    Returns None if below threshold (should not have been accepted).
    Formula: (similarity / 100) × 0.85
    """
    if similarity_score < FUZZY_THRESHOLD:
        return None
    return round((similarity_score / 100) * 0.85, 4)


def arithmetic_confidence(tolerance_used: float = 0.0) -> float:
    """
    Stage 4: arithmetic verification.
    Base 0.95, deduct 0.05 if full tolerance band was consumed.
    tolerance_used: absolute diff between actual and expected net settlement.
    """
    base = 0.95
    if tolerance_used >= AMOUNT_TOLERANCE_INR:
        return round(base - 0.05, 4)
    return base


def ai_confidence_tier() -> tuple[None, str]:
    """
    Stage 5: AI-explained records never receive a numeric confidence score.
    Returns (None, tier_label) to make the absence explicit and intentional.
    """
    return None, "AI-suggested — requires human confirmation"
