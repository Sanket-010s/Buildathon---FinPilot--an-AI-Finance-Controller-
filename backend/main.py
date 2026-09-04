"""
main.py — FastAPI application entrypoint for FinPilot backend.

Run with:
    uvicorn backend.main:app --reload --port 8000

API docs auto-generated at:
    http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routes import audit, exceptions, reconcile

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FinPilot — AI Finance Controller",
    description=(
        "Automated reconciliation engine for orders, payments, settlements, and refunds. "
        "Deterministic-first, AI-last. Every exception is visible — nothing silently dropped."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS — allow Streamlit dashboard on localhost ─────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup: initialise DB tables ─────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()
    print("[FinPilot] Database initialised.")


# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(reconcile.router)
app.include_router(exceptions.router)
app.include_router(audit.router)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
def health():
    """Simple liveness check. Dashboard calls this before rendering."""
    return {"status": "ok", "service": "finpilot-backend"}


@app.get("/", tags=["health"])
def root():
    return {
        "service": "FinPilot — AI Finance Controller",
        "version": "1.0.0",
        "docs": "/docs",
    }
