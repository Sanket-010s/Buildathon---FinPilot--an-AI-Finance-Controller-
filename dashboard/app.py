"""
dashboard/app.py — FinPilot Streamlit Dashboard

Three pages:
    Overview        — aggregate health metrics + stage breakdown chart
    Exceptions List — sortable table of all unresolved exceptions
    Exception Detail — full evidence + AI explanation + action buttons

Design:
    Light theme, vibrant-but-balanced palette (no neon, no dark backgrounds).
    Card-based layout, numbers-first, one chart per page.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import json

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = "http://localhost:8000"

# ── Color palette (from Frontend Documentation) ───────────────────────────────
COLORS = {
    "bg":           "#FAFAFB",
    "card":         "#FFFFFF",
    "sidebar":      "#F1F3F8",
    "text":         "#22242C",
    "meta":         "#7C808A",
    "resolved":     "#22B573",   # fresh emerald
    "exception":    "#F2994A",   # warm amber-orange
    "ai":           "#3B82F6",   # vibrant cobalt blue
    "accent":       "#6C5CE7",   # rich indigo-violet
    "unknown":      "#F2994A",
}

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="FinPilot — AI Finance Controller",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────

st.markdown(f"""
<style>
    /* Base */
    .stApp {{
        background-color: {COLORS['bg']};
        color: {COLORS['text']};
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background-color: {COLORS['sidebar']};
    }}
    [data-testid="stSidebar"] .block-container {{
        padding-top: 2rem;
    }}

    /* Metric cards */
    [data-testid="stMetric"] {{
        background-color: {COLORS['card']};
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }}
    [data-testid="stMetricValue"] {{
        font-size: 2rem !important;
        font-weight: 600;
        color: {COLORS['text']};
    }}
    [data-testid="stMetricLabel"] {{
        color: {COLORS['meta']};
        font-size: 0.82rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}

    /* Card container */
    .fp-card {{
        background-color: {COLORS['card']};
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
    }}

    /* Status chips */
    .chip-resolved {{
        background-color: #E6F9F1;
        color: {COLORS['resolved']};
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }}
    .chip-exception {{
        background-color: #FFF4EB;
        color: {COLORS['exception']};
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }}
    .chip-ai {{
        background-color: #EBF3FF;
        color: {COLORS['ai']};
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }}

    /* Page title */
    .fp-page-title {{
        font-size: 1.6rem;
        font-weight: 600;
        color: {COLORS['text']};
        margin-bottom: 0.2rem;
    }}
    .fp-page-sub {{
        font-size: 0.88rem;
        color: {COLORS['meta']};
        margin-bottom: 1.5rem;
    }}

    /* Stage trail */
    .stage-row {{
        display: flex;
        align-items: flex-start;
        gap: 0.8rem;
        padding: 0.5rem 0;
        border-bottom: 1px solid #F1F3F8;
    }}
    .stage-label {{
        font-size: 0.82rem;
        font-weight: 600;
        color: {COLORS['meta']};
        width: 140px;
        flex-shrink: 0;
    }}
    .stage-reason {{
        font-size: 0.84rem;
        color: {COLORS['text']};
    }}

    /* Divider */
    hr.fp-divider {{
        border: none;
        border-top: 1px solid #ECEEF4;
        margin: 1.2rem 0;
    }}

    /* Hide Streamlit branding */
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    header {{ visibility: hidden; }}
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "overview"
if "selected_record" not in st.session_state:
    st.session_state.selected_record = None


# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(path: str) -> dict | list | None:
    try:
        r = requests.get(f"{BACKEND_URL}{path}", timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except requests.exceptions.ConnectionError:
        return None


def api_post(path: str, payload: dict | None = None) -> dict | None:
    try:
        r = requests.post(f"{BACKEND_URL}{path}", json=payload or {}, timeout=120)
        if r.status_code == 200:
            return r.json()
        st.error(f"API error {r.status_code}: {r.text}")
        return None
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach backend. Make sure `uvicorn backend.main:app --port 8000` is running.")
        return None


def backend_alive() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=4)
        return r.status_code == 200
    except Exception:
        return False


# ── Sidebar navigation ────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style='text-align:center; padding-bottom:1rem;'>
            <span style='font-size:1.7rem;'>💼</span><br>
            <span style='font-size:1.15rem; font-weight:700; color:#22242C;'>FinPilot</span><br>
            <span style='font-size:0.72rem; color:#7C808A; letter-spacing:0.05em;'>AI FINANCE CONTROLLER</span>
        </div>
        <hr style='border:none;border-top:1px solid #DDDFE8;margin:0 0 1rem 0;'>
        """, unsafe_allow_html=True)

        nav_items = [
            ("overview",    "📊", "Overview"),
            ("exceptions",  "⚠️", "Exceptions"),
        ]
        for page_key, icon, label in nav_items:
            is_active = st.session_state.page == page_key or (
                page_key == "exceptions" and st.session_state.page == "detail"
            )
            style = (
                f"background-color:{COLORS['accent']}; color:white;"
                if is_active
                else f"background-color:transparent; color:{COLORS['text']};"
            )
            if st.button(
                f"{icon}  {label}",
                key=f"nav_{page_key}",
                use_container_width=True,
            ):
                st.session_state.page = page_key
                st.session_state.selected_record = None
                st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

        # Run reconciliation button
        st.markdown(
            f"<div style='font-size:0.75rem; color:{COLORS['meta']}; "
            "text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem;'>"
            "Actions</div>",
            unsafe_allow_html=True,
        )
        if st.button("▶  Run Reconciliation", use_container_width=True, type="primary"):
            with st.spinner("Reconciling records…"):
                result = api_post("/reconcile/run")
            if result:
                st.success(
                    f"✅ Done — {result['resolved']}/{result['total_records']} resolved "
                    f"({result['match_rate']*100:.1f}%) in {result['duration_seconds']:.2f}s"
                )
                st.rerun()

        # Status indicator
        alive = backend_alive()
        dot = "🟢" if alive else "🔴"
        status_text = "Backend online" if alive else "Backend offline"
        st.markdown(
            f"<div style='position:absolute; bottom:1.5rem; left:1rem; right:1rem; "
            f"font-size:0.75rem; color:{COLORS['meta']};'>"
            f"{dot} {status_text}<br>"
            f"<span style='font-size:0.7rem;'>localhost:8000</span></div>",
            unsafe_allow_html=True,
        )


# ── Page: Overview ────────────────────────────────────────────────────────────

def page_overview():
    st.markdown('<p class="fp-page-title">Reconciliation Overview</p>', unsafe_allow_html=True)

    summary = api_get("/reconcile/summary")

    if summary is None:
        st.info(
            "No reconciliation data yet. Click **▶ Run Reconciliation** in the sidebar to start.",
            icon="ℹ️",
        )
        st.markdown(
            "<div class='fp-card'>"
            "<p style='color:#7C808A; font-size:0.9rem; margin:0;'>"
            "FinPilot will process your synthetic data through a 5-stage deterministic pipeline "
            "and surface any exceptions that need human review."
            "</p></div>",
            unsafe_allow_html=True,
        )
        return

    by_stage = summary.get("by_stage", {})
    match_rate_pct = round(summary.get("match_rate", 0) * 100, 1)

    # Last-run timestamp helper
    st.markdown(
        f"<p class='fp-page-sub'>Last run results · "
        f"{summary['total_records']} records processed</p>",
        unsafe_allow_html=True,
    )

    # ── Headline metric cards ─────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Records", f"{summary['total_records']:,}")
    with col2:
        st.metric("Match Rate", f"{match_rate_pct}%")
    with col3:
        st.metric(
            "Exceptions",
            f"{summary['exceptions']:,}",
            delta=f"-{summary['exceptions']} need review",
            delta_color="inverse",
        )
    with col4:
        st.metric(
            "Total Reconciled",
            f"₹{summary.get('total_settled_amount', 0):,.2f}",
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Stage breakdown chart ─────────────────────────────────────────────────
    st.markdown('<div class="fp-card">', unsafe_allow_html=True)
    st.markdown(
        f"<p style='font-weight:600; font-size:1rem; color:{COLORS['text']}; margin-bottom:0.8rem;'>"
        "Match Stage Breakdown</p>",
        unsafe_allow_html=True,
    )

    stage_labels = {
        "exact":        "Exact Match",
        "attribute":    "Attribute Match",
        "fuzzy":        "Fuzzy Match",
        "arithmetic":   "Arithmetic Verify",
        "ai_explained": "AI-Explained",
        "unresolved":   "Unresolved",
    }
    stage_colors_map = {
        "exact":        COLORS["resolved"],
        "attribute":    "#34D399",
        "fuzzy":        "#60A5FA",
        "arithmetic":   "#818CF8",
        "ai_explained": COLORS["ai"],
        "unresolved":   COLORS["exception"],
    }

    chart_data = {
        stage_labels[k]: by_stage.get(k, 0)
        for k in stage_labels
        if by_stage.get(k, 0) > 0
    }

    if chart_data:
        import pandas as pd

        chart_df = pd.DataFrame({
            "Stage": list(chart_data.keys()),
            "Count": list(chart_data.values()),
        }).set_index("Stage")
        st.bar_chart(chart_df, color=COLORS["accent"])
    else:
        st.caption("No stage data available.")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Secondary stats row ───────────────────────────────────────────────────
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(
            f"<div class='fp-card'>"
            f"<p style='font-size:0.8rem;color:{COLORS['meta']};text-transform:uppercase;"
            f"letter-spacing:0.05em;margin-bottom:0.3rem;'>Total Refunds</p>"
            f"<p style='font-size:1.5rem;font-weight:600;color:{COLORS['text']};margin:0;'>"
            f"₹{summary.get('total_refunds', 0):,.2f}</p></div>",
            unsafe_allow_html=True,
        )
    with col_b:
        st.markdown(
            f"<div class='fp-card'>"
            f"<p style='font-size:0.8rem;color:{COLORS['meta']};text-transform:uppercase;"
            f"letter-spacing:0.05em;margin-bottom:0.3rem;'>Silent Failures Detected</p>"
            f"<p style='font-size:1.5rem;font-weight:600;color:{COLORS['exception']};margin:0;'>"
            f"{summary.get('silent_failures', 0)}</p></div>",
            unsafe_allow_html=True,
        )
    with col_c:
        st.markdown(
            f"<div class='fp-card'>"
            f"<p style='font-size:0.8rem;color:{COLORS['meta']};text-transform:uppercase;"
            f"letter-spacing:0.05em;margin-bottom:0.3rem;'>AI-Explained</p>"
            f"<p style='font-size:1.5rem;font-weight:600;color:{COLORS['ai']};margin:0;'>"
            f"{by_stage.get('ai_explained', 0)}</p></div>",
            unsafe_allow_html=True,
        )

    # Footer note
    st.markdown(
        f"<p style='font-size:0.72rem; color:{COLORS['meta']}; margin-top:1rem;'>"
        "⚠️ All data is synthetically generated for demonstration purposes only.</p>",
        unsafe_allow_html=True,
    )


# ── Page: Exceptions List ─────────────────────────────────────────────────────

def page_exceptions():
    st.markdown('<p class="fp-page-title">Exceptions</p>', unsafe_allow_html=True)

    exceptions = api_get("/exceptions")

    if exceptions is None:
        st.error("Could not load exceptions. Is the backend running?")
        return

    if not exceptions:
        st.success("✅ No exceptions found! All records have been reconciled.")
        return

    total = len(exceptions)
    st.markdown(
        f"<p class='fp-page-sub'>{total} record{'s' if total != 1 else ''} require human review</p>",
        unsafe_allow_html=True,
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        status_filter = st.selectbox(
            "Status",
            ["All", "AI-Explained", "Unknown"],
            key="exc_status_filter",
        )
    with col_f2:
        stage_options = sorted(set(e.get("stage_reached", "") for e in exceptions))
        stage_filter = st.selectbox(
            "Stage Reached",
            ["All"] + stage_options,
            key="exc_stage_filter",
        )
    with col_f3:
        amounts = [e.get("order_amount") or 0 for e in exceptions]
        max_amt = max(amounts) if amounts else 10000
        amount_range = st.slider(
            "Amount Range (₹)",
            0.0, float(max_amt),
            (0.0, float(max_amt)),
            key="exc_amount_filter",
        )

    # Apply filters
    filtered = exceptions
    if status_filter != "All":
        if status_filter == "AI-Explained":
            filtered = [e for e in filtered if e.get("stage_reached") == "ai"]
        elif status_filter == "Unknown":
            filtered = [e for e in filtered if e.get("stage_reached") == "unresolved"]
    if stage_filter != "All":
        filtered = [e for e in filtered if e.get("stage_reached") == stage_filter]
    filtered = [
        e for e in filtered
        if amount_range[0] <= (e.get("order_amount") or 0) <= amount_range[1]
    ]

    st.markdown(f"<p style='font-size:0.8rem;color:{COLORS['meta']};'>Showing {len(filtered)} of {total}</p>", unsafe_allow_html=True)

    if not filtered:
        st.info("No records match the current filters.")
        return

    # ── Table ─────────────────────────────────────────────────────────────────
    import pandas as pd

    rows = []
    for e in filtered:
        stage = e.get("stage_reached", "")
        tier = e.get("confidence_tier", "")
        if stage == "ai":
            status_label = "AI-Explained"
        elif stage == "unresolved":
            status_label = "Unknown"
        else:
            status_label = stage.title()

        hr = e.get("human_review_status")
        review_label = ""
        if hr == "resolved_manual":
            review_label = "✅ Resolved"
        elif hr == "escalated":
            review_label = "🔺 Escalated"

        rows.append({
            "Record ID":    e.get("record_id", ""),
            "Amount (₹)":  f"₹{e.get('order_amount', 0):,.2f}" if e.get("order_amount") else "—",
            "Date":         e.get("order_date", "—"),
            "Stage Reached": stage.upper(),
            "Status":       status_label,
            "Review":       review_label,
        })

    df = pd.DataFrame(rows)

    # Render table inside a card
    st.markdown('<div class="fp-card" style="padding:0.5rem 1rem;">', unsafe_allow_html=True)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Amount (₹)": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.TextColumn(width="small"),
            "Stage Reached": st.column_config.TextColumn(width="medium"),
        },
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Row click → detail ────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f"<p style='font-size:0.82rem; color:{COLORS['meta']};'>"
        "Select a record to view full details:</p>",
        unsafe_allow_html=True,
    )

    record_ids = [e.get("record_id", "") for e in filtered]
    selected = st.selectbox("Record ID", record_ids, key="exc_select", label_visibility="collapsed")

    if st.button("View Exception Detail →", type="primary", key="view_detail_btn"):
        st.session_state.selected_record = selected
        st.session_state.page = "detail"
        st.rerun()


# ── Page: Exception Detail ────────────────────────────────────────────────────

def page_detail():
    record_id = st.session_state.selected_record

    if not record_id:
        st.session_state.page = "exceptions"
        st.rerun()
        return

    # Back button
    if st.button("← Back to Exceptions", key="back_btn"):
        st.session_state.page = "exceptions"
        st.session_state.selected_record = None
        st.rerun()

    data = api_get(f"/exceptions/{record_id}")

    if data is None:
        st.error(f"Could not load detail for record {record_id}.")
        return

    audit = api_get(f"/records/{record_id}/audit") or {}
    audit_entries = audit.get("entries", [])

    # Determine status chip
    stage = data.get("final_stage", "")
    if stage == "ai":
        status_chip = f"<span class='chip-ai'>AI-Explained — needs confirmation</span>"
    elif stage == "unresolved":
        status_chip = f"<span class='chip-exception'>Unknown Exception</span>"
    else:
        status_chip = f"<span class='chip-exception'>Exception</span>"

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        f"<p class='fp-page-title'>{record_id} &nbsp; {status_chip}</p>",
        unsafe_allow_html=True,
    )
    if data.get("silent_failure"):
        st.warning(
            "⚠️ Silent failure detected — order was marked 'failed' but payment was captured.",
            icon="⚠️",
        )

    # ── Record summary card ───────────────────────────────────────────────────
    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.markdown('<div class="fp-card">', unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-weight:600;font-size:0.9rem;color:{COLORS['text']};margin-bottom:0.8rem;'>"
            "Order Summary</p>",
            unsafe_allow_html=True,
        )

        def kv(label, value, highlight=False):
            color = COLORS["text"] if not highlight else COLORS["accent"]
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:0.35rem 0;border-bottom:1px solid #F1F3F8;'>"
                f"<span style='font-size:0.82rem;color:{COLORS['meta']};'>{label}</span>"
                f"<span style='font-size:0.84rem;font-weight:600;color:{color};'>{value}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        kv("Order ID", data.get("order_id", "—"))
        kv("Amount", f"₹{data.get('order_amount', 0):,.2f}" if data.get("order_amount") else "—", highlight=True)
        kv("Order Date", data.get("order_date", "—"))
        kv("Customer ID", data.get("customer_id", "—"))
        kv("Gateway", data.get("gateway", "—"))
        kv("Order Status", data.get("order_status", "—"))
        kv("Payment ID", data.get("payment_id") or "Not found")
        kv("Payment Amount", f"₹{data.get('payment_amount', 0):,.2f}" if data.get("payment_amount") else "—")
        kv("Payment Status", data.get("payment_status") or "—")
        kv("Settlement ID", data.get("settlement_id") or "Not found")
        kv("Settlement Net", f"₹{data.get('settlement_net', 0):,.2f}" if data.get("settlement_net") else "—")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_right:
        # ── Stage attempt trail ───────────────────────────────────────────────
        st.markdown('<div class="fp-card">', unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-weight:600;font-size:0.9rem;color:{COLORS['text']};margin-bottom:0.8rem;'>"
            "Reconciliation Attempts</p>",
            unsafe_allow_html=True,
        )

        stage_display = {
            "exact":      "Exact Match",
            "attribute":  "Attribute Match",
            "fuzzy":      "Fuzzy Match",
            "arithmetic": "Arithmetic Check",
            "ai":         "AI Explanation",
            "unresolved": "Unresolved",
        }

        if audit_entries:
            for entry in audit_entries:
                s_label = stage_display.get(entry.get("stage", ""), entry.get("stage", "").title())
                reasoning = entry.get("reasoning", "")
                dur = entry.get("duration_ms")
                dur_str = f" · {dur:.1f}ms" if dur else ""
                st.markdown(
                    f"<div class='stage-row'>"
                    f"<span class='stage-label'>{s_label}</span>"
                    f"<span class='stage-reason'>{reasoning}{dur_str}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No audit trail entries found.")

        st.markdown('</div>', unsafe_allow_html=True)

    # ── AI Explanation block ──────────────────────────────────────────────────
    if data.get("ai_explanation"):
        st.markdown('<div class="fp-card">', unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-weight:600;font-size:0.9rem;color:{COLORS['ai']};margin-bottom:0.5rem;'>"
            "🤖 AI Explanation</p>"
            f"<p style='font-size:0.78rem;color:{COLORS['meta']};margin-bottom:0.8rem;font-style:italic;'>"
            "AI-suggested — requires human confirmation. The AI explains; it does not resolve.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='font-size:0.9rem;color:{COLORS['text']};line-height:1.6;'>"
            f"{data['ai_explanation']}</p>",
            unsafe_allow_html=True,
        )

        # Candidates
        candidates = data.get("candidates_considered", [])
        if candidates:
            st.markdown(
                f"<p style='font-size:0.8rem;font-weight:600;color:{COLORS['meta']};"
                "margin-top:1rem;margin-bottom:0.4rem;'>Candidates considered:</p>",
                unsafe_allow_html=True,
            )
            for c in candidates:
                amt_str = f"₹{c['amount']:,.2f}" if c.get("amount") else "—"
                st.markdown(
                    f"<div style='font-size:0.82rem;padding:0.3rem 0;'>"
                    f"<b>{c.get('source','').upper()}</b> {c.get('id','—')} "
                    f"· {amt_str} · {c.get('date','—')}</div>",
                    unsafe_allow_html=True,
                )

        st.markdown('</div>', unsafe_allow_html=True)

    # ── Action row ────────────────────────────────────────────────────────────
    current_review = data.get("human_review_status")

    st.markdown('<div class="fp-card">', unsafe_allow_html=True)
    st.markdown(
        f"<p style='font-weight:600;font-size:0.9rem;color:{COLORS['text']};margin-bottom:0.8rem;'>"
        "Human Review Decision</p>",
        unsafe_allow_html=True,
    )

    if current_review:
        review_labels = {
            "resolved_manual": "✅ Marked as Resolved (Manual)",
            "escalated": "🔺 Escalated for further review",
        }
        st.success(review_labels.get(current_review, current_review))
    else:
        col_act1, col_act2, col_spacer = st.columns([1, 1, 3])
        with col_act1:
            if st.button("✅ Mark Resolved (Manual)", key="resolve_btn", use_container_width=True):
                result = api_post(
                    f"/exceptions/{record_id}/review",
                    {"action": "resolved_manual"},
                )
                if result:
                    st.success("Marked as resolved.")
                    st.rerun()
        with col_act2:
            if st.button("🔺 Escalate", key="escalate_btn", use_container_width=True):
                result = api_post(
                    f"/exceptions/{record_id}/review",
                    {"action": "escalated"},
                )
                if result:
                    st.warning("Escalated for further review.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ── Router ────────────────────────────────────────────────────────────────────

render_sidebar()

page = st.session_state.page

if page == "overview":
    page_overview()
elif page == "exceptions":
    page_exceptions()
elif page == "detail":
    page_detail()
else:
    page_overview()
