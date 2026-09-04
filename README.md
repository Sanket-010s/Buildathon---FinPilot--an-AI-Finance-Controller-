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
# Edit .env and add your GEMINI_API_KEY or OPENAI_API_KEY

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
│   ├── main.py                  # FastAPI app entrypoint
│   ├── config.py                # Settings loaded from .env
│   ├── database.py              # SQLite connection + persistence layer
│   ├── engine/
│   │   ├── normalize.py          # Multi-gateway data normalization
│   │   ├── stage1_exact.py       # Stage 1: Exact ID match
│   │   ├── stage2_attribute.py   # Stage 2: Amount + date + customer match
│   │   ├── stage3_fuzzy.py       # Stage 3: RapidFuzz text similarity
│   │   ├── stage4_arithmetic.py  # Stage 4: Net = Order - MDR - GST - Refund
│   │   ├── stage5_ai.py          # Stage 5: LLM explanation (last resort)
│   │   ├── candidate_retriever.py # Finds nearby records for AI context
│   │   └── pipeline.py           # Orchestrates stages 1-5
│   ├── models/
│   │   ├── schema.py             # SQLAlchemy ORM table definitions
│   │   └── pydantic_models.py    # FastAPI request/response schemas
│   ├── routes/
│   │   ├── reconcile.py          # POST /reconcile/run, GET /reconcile/summary
│   │   ├── exceptions.py         # GET /exceptions, GET /exceptions/{id}
│   │   └── audit.py              # GET /records/{id}/audit
│   └── utils/
│       ├── confidence.py         # Deterministic confidence scoring rules
│       └── logger.py             # Audit log writer + StageTimer
├── data/
│   ├── synthetic_generator.py   # Generates 200+ realistic synthetic records
│   ├── orders.csv
│   ├── payments.csv
│   ├── settlements.csv
│   └── refunds.csv
├── dashboard/
│   └── app.py                   # Streamlit dashboard (3 pages)
├── finpilot.db                  # SQLite database (auto-created)
├── requirements.txt
└── .env.example
```

---

## Reconciliation Pipeline

Records are processed in strict order — resolved at the first successful stage:

| Stage | Method | Confidence |
|---|---|---|
| 1. Exact Match | Transaction IDs align across all sources | 1.00 |
| 2. Attribute Match | Amount + date (±3 days) + customer match | 0.90 − 0.02/day drift |
| 3. Fuzzy Match | RapidFuzz similarity ≥ 85 on reference strings | (score/100) × 0.85 |
| 4. Arithmetic Verify | `Order − MDR(2%) − GST(18%) − Refund = Net Settlement` within ₹1 | 0.95 |
| 5. AI Explanation | LLM explains the discrepancy — **never asserts a match** | N/A (human confirms) |

Any record that fails all 5 stages is tagged **EXCEPTION (Unknown)** and shown in the Exceptions tab — never silently dropped.

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

Interactive API docs: **http://localhost:8000/docs**

---

## Dashboard Pages

- **Overview** — Match rate, per-stage breakdown chart, total amount reconciled, silent failures
- **Exceptions List** — Filterable table of all unresolved records (filter by status, stage, amount)
- **Exception Detail** — Full record data, stage attempt trail, AI explanation, Mark Resolved / Escalate buttons

---

## Demo Results (220 records)

```
Stage 1 (Exact):        184 resolved
Stage 2 (Attribute):     18 resolved
Stage 3 (Fuzzy):          0 resolved
Stage 4 (Arithmetic):     4 resolved
Stage 5 (AI):             0 explained  (no LLM key = no AI calls)
Unresolved Exceptions:   14
-------------------------------
Match Rate: 93.6%  |  Total: ₹10,31,589.65 reconciled  |  Refunds: ₹45,541.75
Silent failures detected: 3
```

---
