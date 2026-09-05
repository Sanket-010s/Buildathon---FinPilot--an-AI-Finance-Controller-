"""
routes/reconcile.py — /reconcile/* endpoints
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import database as db_module
from backend.config import DB_PATH
from backend.engine import normalize
from backend.engine.pipeline import run_pipeline_from_dfs
from backend.models.pydantic_models import RunResponse, SummaryResponse, StageSummary

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


@router.post("/run", response_model=RunResponse)
def run_reconciliation(db: Session = Depends(db_module.get_db)):
    """
    Trigger a full reconciliation run over the current dataset.
    Loads CSVs, runs all 5 stages, persists to DB, returns summary.
    """
    try:
        orders_df, payments_df, settlements_df, refunds_df = normalize.load_and_normalize()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = run_pipeline_from_dfs(orders_df, payments_df, settlements_df, refunds_df)

    # Persist source data and pipeline results
    db_module.persist_source_data(orders_df, payments_df, settlements_df, refunds_df, db)
    db_module.persist_pipeline_result(result, db)

    summary = result.summary()
    return RunResponse(
        status="completed",
        total_records=summary["total_records"],
        resolved=summary["resolved"],
        exceptions=summary["exceptions"],
        match_rate=summary["match_rate"],
        duration_seconds=summary["duration_seconds"],
    )


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(db_module.get_db)):
    """Return aggregate breakdown by stage from the last run."""
    data = db_module.get_summary(db)
    if data["total_records"] == 0:
        raise HTTPException(
            status_code=404,
            detail="No reconciliation data found. Run POST /reconcile/run first."
        )
    return SummaryResponse(
        total_records=data["total_records"],
        resolved=data["resolved"],
        exceptions=data["exceptions"],
        match_rate=data["match_rate"],
        duration_seconds=data["duration_seconds"],
        by_stage=StageSummary(**data["by_stage"]),
        total_settled_amount=data["total_settled_amount"],
        total_refunds=data["total_refunds"],
        silent_failures=data["silent_failures"],
    )


@router.get("/records")
def get_all_records(db: Session = Depends(db_module.get_db)):
    """Return all reconciliation records for the overview table."""
    return db_module.get_all_records(db)
