"""
routes/exceptions.py — /exceptions/* endpoints
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import database as db_module
from backend.models.pydantic_models import (
    CandidateRecord,
    ExceptionDetail,
    ExceptionItem,
    ReviewAction,
    ReviewResponse,
)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("", response_model=list[ExceptionItem])
def list_exceptions(db: Session = Depends(db_module.get_db)):
    """Return all unresolved exception records."""
    rows = db_module.get_exceptions(db)
    return [ExceptionItem(**r) for r in rows]


@router.get("/{record_id}", response_model=ExceptionDetail)
def get_exception(record_id: str, db: Session = Depends(db_module.get_db)):
    """Full detail for one exception: attempts made, AI explanation, candidates."""
    data = db_module.get_exception_detail(record_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Exception record '{record_id}' not found.")

    # Coerce candidates_considered to CandidateRecord list
    candidates = [CandidateRecord(**c) for c in data.get("candidates_considered", [])]
    data["candidates_considered"] = candidates
    return ExceptionDetail(**data)


@router.post("/{record_id}/review", response_model=ReviewResponse)
def submit_review(
    record_id: str,
    body: ReviewAction,
    db: Session = Depends(db_module.get_db),
):
    """
    Submit a human review decision for an exception.
    Action must be 'resolved_manual' or 'escalated'.
    """
    valid_actions = {"resolved_manual", "escalated"}
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{body.action}'. Must be one of: {valid_actions}",
        )
    result = db_module.update_human_review(record_id, body.action, db)
    if not result:
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found.")

    return ReviewResponse(
        record_id=result["record_id"],
        human_review_status=result["human_review_status"],
        human_review_at=result["human_review_at"],
        message=f"Record {record_id} marked as '{body.action}' successfully.",
    )
