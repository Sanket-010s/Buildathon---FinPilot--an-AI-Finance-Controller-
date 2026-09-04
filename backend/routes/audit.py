"""
routes/audit.py — /records/{record_id}/audit endpoint
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import database as db_module
from backend.models.pydantic_models import AuditEntry, AuditTrailResponse

router = APIRouter(prefix="/records", tags=["audit"])


@router.get("/{record_id}/audit", response_model=AuditTrailResponse)
def get_audit_trail(record_id: str, db: Session = Depends(db_module.get_db)):
    """
    Return the full chronological audit trail for a single record.
    Every stage attempted, reasoning, timestamps, and AI explanation if reached.
    """
    entries = db_module.get_audit_trail(record_id, db)
    if not entries:
        raise HTTPException(
            status_code=404,
            detail=f"No audit trail found for record '{record_id}'. "
                   "Ensure a reconciliation run has been completed."
        )
    return AuditTrailResponse(
        record_id=record_id,
        entries=[AuditEntry(**e) for e in entries],
    )
