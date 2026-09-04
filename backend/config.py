"""
config.py — Central settings loader for FinPilot backend.
All configuration is read from environment variables (via .env).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "finpilot.db")

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "openai"
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ── Reconciliation thresholds ─────────────────────────────────────────────────
DATE_TOLERANCE_DAYS: int = int(os.getenv("DATE_TOLERANCE_DAYS", "3"))
AMOUNT_TOLERANCE_INR: float = float(os.getenv("AMOUNT_TOLERANCE_INR", "1.0"))
FUZZY_THRESHOLD: int = int(os.getenv("FUZZY_THRESHOLD", "85"))

# MDR fee rates (applied during arithmetic verification)
MDR_RATE: float = 0.02          # 2% of order amount
GST_ON_MDR_RATE: float = 0.18   # 18% GST on MDR fee

# ── Backend server ────────────────────────────────────────────────────────────
BACKEND_HOST: str = os.getenv("BACKEND_HOST", "localhost")
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_URL: str = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

# ── AI Stage ──────────────────────────────────────────────────────────────────
AI_CANDIDATE_WINDOW_DAYS: int = 7       # date window for candidate retrieval
AI_CANDIDATE_AMOUNT_PCT: float = 0.15   # ±15% amount window for candidates
AI_MAX_CANDIDATES: int = 3
LLM_TIMEOUT_SECONDS: int = 30
