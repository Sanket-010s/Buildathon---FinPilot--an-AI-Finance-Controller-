# FinPilot — AI Finance Controller
**Razorpay Buildathon 2026**

> *Because your money deserves to be understood.*

FinPilot automatically reconciles merchant orders, payments, settlements, and refunds
using a deterministic-first 5-stage pipeline. AI is used only as a last-resort explainer —
never as a decision-maker. Every exception is visible. Nothing is silently dropped.

---

## Quick Start

```bash
# 1. Clone and enter the project
cd finpilot

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env
# Edit .env — add your GEMINI_API_KEY or OPENAI_API_KEY

# 5. Generate synthetic data (220 records)
python data/synthetic_generator.py --records 220

# 6. Start the backend (Terminal 1)
uvicorn backend.main:app --reload --port 8000

# 7. Start the dashboard (Terminal 2)
streamlit run dashboard/app.py
```

Open **http://localhost:8501** in your browser, then click **▶ Run Reconciliation** in the sidebar.

---

## Project Structure

```
finpilot/
├── backend/
│   ├── main.py                    # FastAPI app entrypoint (v1.0.0)
│   ├── config.py                  # Settings from .env — DB, LLM, thresholds
│   ├── database.py                # SQLite connection, ORM persistence, query helpers
│   ├── engine/
│   │   ├── normalize.py           # Multi-gateway data normalization
│   │   ├── stage1_exact.py        # Stage 1: Exact ID match
│   │   ├── stage2_attribute.py    # Stage 2: Amount + date + customer match
│   │   ├── stage3_fuzzy.py        # Stage 3: RapidFuzz text similarity
│   │   ├── stage4_arithmetic.py   # Stage 4: Net = Order − MDR − GST − Refund
│   │   ├── stage5_ai.py           # Stage 5: LLM explanation (Gemini / OpenAI)
│   │   ├── candidate_retriever.py # Retrieves nearby records as LLM context
│   │   └── pipeline.py            # Orchestrates stages 1–5 → PipelineResult
│   ├── models/
│   │   ├── schema.py              # SQLAlchemy ORM table definitions
│   │   └── pydantic_models.py     # FastAPI request/response schemas
│   ├── routes/
│   │   ├── reconcile.py           # POST /reconcile/run, GET /reconcile/summary
│   │   ├── exceptions.py          # GET /exceptions, GET /exceptions/{id}
│   │   └── audit.py               # GET /records/{id}/audit
│   └── utils/
│       ├── confidence.py          # Deterministic confidence scoring rules
│       └── logger.py              # Audit log writer + StageTimer
├── data/
│   ├── synthetic_generator.py     # Generates 200+ realistic synthetic records
│   ├── orders.csv
│   ├── payments.csv
│   ├── settlements.csv
│   └── refunds.csv
├── dashboard/
│   └── app.py                     # Streamlit dashboard (3 pages)
├── finpilot.db                    # SQLite database (auto-created on first run)
├── requirements.txt
└── .env.example
```

---

## Reconciliation Pipeline

Records are processed in strict order — resolved at the first successful stage:

| Stage | Method | Confidence |
|---|---|---|
| 1 · Exact Match | Transaction IDs align across all sources | 1.00 |
| 2 · Attribute Match | Amount + date (±3 days) + customer match | 0.90 − 0.02/day drift |
| 3 · Fuzzy Match | RapidFuzz similarity ≥ 85 on reference strings | (score / 100) × 0.85 |
| 4 · Arithmetic Verify | `Order − MDR(2%) − GST(18%) − Refund = Net Settlement` within ₹1 | 0.95 |
| 5 · AI Explanation | LLM explains the discrepancy — **never asserts a match** | N/A (human confirms) |

Any record that fails all 5 stages is tagged **EXCEPTION (Unknown)** and shown in the Exceptions tab — never silently dropped.

---

## LLM Integration (Stage 5)

Stage 5 is the only place AI is involved. It is deliberately constrained:

**What the LLM does**
- Receives the unresolved record + up to 3 nearby candidate records (retrieved by a ±7-day date window and ±15% amount window).
- Produces a plain-text explanation (≤ 3 sentences) of *why* the record likely failed reconciliation.
- References candidate record IDs if they informed the reasoning.

**What the LLM never does**
- Assert a definitive match or assign a confidence score.
- Silently drop or hide a record.
- Act without a human review step — AI-explained records still require manual confirmation.

**Supported providers**

| Provider | Model | Role |
|---|---|---|
| Google Gemini | `gemini-1.5-flash` | Primary |
| OpenAI | `gpt-4o-mini` | Fallback |

Provider selection is controlled by `LLM_PROVIDER` in `.env`. The system falls back to OpenAI automatically if Gemini is unavailable. If neither key is set, the record is tagged `EXCEPTION (Unknown)` — no silent failures.

**Configuration knobs** (all in `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Active provider: `gemini` or `openai` |
| `GEMINI_API_KEY` | — | Google AI Studio key |
| `OPENAI_API_KEY` | — | OpenAI platform key |
| `AI_CANDIDATE_WINDOW_DAYS` | `7` | Date window for candidate retrieval |
| `AI_CANDIDATE_AMOUNT_PCT` | `0.15` | ±15% amount band for candidates |
| `AI_MAX_CANDIDATES` | `3` | Max candidates passed to the LLM |
| `LLM_TIMEOUT_SECONDS` | `30` | Hard timeout per LLM call |

---

## Configuration Reference

Full `.env` reference (copy from `.env.example`):

```env
# LLM Provider
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
LLM_PROVIDER=gemini          # "gemini" | "openai"

# Database
DB_PATH=finpilot.db

# Reconciliation thresholds
DATE_TOLERANCE_DAYS=3
AMOUNT_TOLERANCE_INR=1.0
FUZZY_THRESHOLD=85

# Backend server
BACKEND_HOST=localhost
BACKEND_PORT=8000
```

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/reconcile/run` | Trigger a full reconciliation run |
| `GET` | `/reconcile/summary` | Aggregate stats by stage |
| `GET` | `/exceptions` | All unresolved exception records |
| `GET` | `/exceptions/{id}` | Full detail + AI explanation for one exception |
| `POST` | `/exceptions/{id}/review` | Submit human review decision |
| `GET` | `/records/{id}/audit` | Full audit trail for any record |
| `GET` | `/health` | Liveness check |

Interactive API docs: **http://localhost:8000/docs** · ReDoc: **http://localhost:8000/redoc**

---

## Dashboard Pages

- **Overview** — Match rate, per-stage breakdown chart, total amount reconciled, silent failure count
- **Exceptions List** — Filterable table of all unresolved records (filter by status, stage, amount range)
- **Exception Detail** — Full record data, stage attempt trail, AI explanation panel, Mark Resolved / Escalate actions

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI 0.111 + Uvicorn |
| Database | SQLite via SQLAlchemy 2.0 |
| Reconciliation | pandas 2.2, RapidFuzz 3.9 |
| LLM — Primary | Google Generative AI (`google-generativeai` 0.7) |
| LLM — Fallback | OpenAI Python SDK (`openai` 1.30) |
| Dashboard | Streamlit 1.35 |
| Data validation | Pydantic v2 |

---

## Demo Results (220 records)

```
Stage 1 (Exact):        184 resolved
Stage 2 (Attribute):     18 resolved
Stage 3 (Fuzzy):          0 resolved
Stage 4 (Arithmetic):     4 resolved
Stage 5 (AI):             0 explained  ← requires a configured LLM key
Unresolved Exceptions:   14
─────────────────────────────────────────────
Match Rate:   93.6%
Reconciled:   ₹10,31,589.65
Refunds:      ₹45,541.75
Silent failures detected: 3
```

> Stage 5 shows 0 because no LLM key was set during this run. Add `GEMINI_API_KEY` or `OPENAI_API_KEY` to `.env` to enable AI explanations for the 14 unresolved exceptions.

---

## Design Principles

1. **Deterministic first** — AI is the last resort, not the first.
2. **No silent drops** — every record ends in a known state: Resolved, AI-explained (pending review), or Exception (Unknown).
3. **Auditable** — every stage attempt is written to the audit log with timing, reasoning, and candidates considered.
4. **Human in the loop** — AI explanations require a human `Mark Resolved` or `Escalate` action before a record is closed.
