"""
stage5_ai.py — Stage 5: AI Explanation (Last Resort)

Only invoked for records that failed all four deterministic stages.
The LLM is given the unresolved record + retrieved candidate context
and is prompted to EXPLAIN the discrepancy — never to assert a match.

Key rules (hardcoded, not LLM-controlled):
  - LLM output is stored as explanation text only.
  - Confidence score is NEVER assigned by the LLM.
  - If the LLM cannot explain, or the API call fails, the record is
    tagged EXCEPTION ("Unknown") — never silently dropped.
  - The stage fails gracefully on timeout/network error.

Contract:
    explain(unified_df, settlements_df, payments_df, refunds_df)
        -> (ai_explained_df, exceptions_df)

Supported providers: Gemini 1.5 Flash (primary), GPT-4o-mini (fallback).
"""

from __future__ import annotations

import json

import pandas as pd

from backend.config import (
    GEMINI_API_KEY,
    LLM_PROVIDER,
    LLM_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
)
from backend.engine.candidate_retriever import retrieve_candidates
from backend.utils.confidence import ai_confidence_tier
from backend.utils.logger import StageTimer, write as audit_write

STAGE_NAME = "ai"

SYSTEM_PROMPT = """You are a financial reconciliation assistant.
Your ONLY job is to explain WHY a transaction record could not be automatically reconciled.
STRICT rules you must follow:
1. Do NOT assert a definitive match. Only explain possible reasons for the discrepancy.
2. Reference specific candidate records (by their ID) if they informed your reasoning.
3. If you cannot find a plausible explanation, say exactly: "cannot determine"
4. Keep your explanation under 3 sentences.
5. Never invent data not present in the context provided."""


def explain(
    unified_df: pd.DataFrame,
    settlements_df: pd.DataFrame,
    payments_df: pd.DataFrame | None = None,
    refunds_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Stage 5: AI Explanation.

    Args:
        unified_df:      Records still unresolved after all deterministic stages.
        settlements_df:  Full normalised settlements.
        payments_df:     Full normalised payments (for candidate retrieval).
        refunds_df:      Full normalised refunds (for candidate retrieval).

    Returns:
        (ai_explained_df, exceptions_df)
        - ai_explained_df: records where LLM produced an explanation
          (status = "EXCEPTION", match_stage = "ai", needs human confirmation)
        - exceptions_df:   records where LLM could not explain or call failed
          (status = "EXCEPTION", match_stage = "unresolved")
    """
    ai_explained_rows: list[pd.Series] = []
    exceptions_rows: list[pd.Series] = []

    for _, row in unified_df.iterrows():
        record_id = str(row.get("record_id", row.get("order_id", "UNKNOWN")))

        with StageTimer() as timer:
            candidates = retrieve_candidates(
                row, settlements_df, payments_df, refunds_df
            )
            explanation_result = _call_llm(row, candidates)

        _, ai_tier = ai_confidence_tier()
        candidate_ids = [c["id"] for c in candidates]

        if explanation_result["success"] and explanation_result["explanation"] != "cannot determine":
            audit_write(
                record_id=record_id,
                stage=STAGE_NAME,
                reasoning=f"AI explanation generated. Tier: {ai_tier}",
                candidates_considered=candidate_ids,
                ai_explanation=explanation_result["explanation"],
                duration_ms=timer.elapsed_ms,
            )
            row = row.copy()
            row["match_stage"] = STAGE_NAME
            row["confidence_score"] = None  # Never a model-generated number
            row["confidence_tier"] = ai_tier
            row["match_status"] = "EXCEPTION"
            row["ai_explanation"] = explanation_result["explanation"]
            row["ai_candidates"] = json.dumps(candidates)
            ai_explained_rows.append(row)
        else:
            reason = (
                explanation_result.get("error") or
                "AI could not find a plausible explanation for this discrepancy."
            )
            audit_write(
                record_id=record_id,
                stage="unresolved",
                reasoning=reason,
                candidates_considered=candidate_ids,
                ai_explanation=None,
                duration_ms=timer.elapsed_ms,
            )
            row = row.copy()
            row["match_stage"] = "unresolved"
            row["confidence_score"] = None
            row["confidence_tier"] = "Unknown"
            row["match_status"] = "EXCEPTION"
            row["ai_explanation"] = None
            row["ai_candidates"] = json.dumps(candidates)
            exceptions_rows.append(row)

    ai_explained_df = pd.DataFrame(ai_explained_rows) if ai_explained_rows else _empty_frame(unified_df)
    exceptions_df = pd.DataFrame(exceptions_rows) if exceptions_rows else _empty_frame(unified_df)

    return ai_explained_df, exceptions_df


def _call_llm(row: pd.Series, candidates: list[dict]) -> dict:
    """
    Call the configured LLM provider.
    Returns: {success: bool, explanation: str | None, error: str | None}
    """
    prompt = _build_prompt(row, candidates)

    if LLM_PROVIDER == "gemini" and GEMINI_API_KEY:
        return _call_gemini(prompt)
    elif LLM_PROVIDER == "openai" and OPENAI_API_KEY:
        return _call_openai(prompt)
    else:
        return {
            "success": False,
            "explanation": None,
            "error": "No LLM provider configured. Set GEMINI_API_KEY or OPENAI_API_KEY in .env",
        }


def _build_prompt(row: pd.Series, candidates: list[dict]) -> str:
    """Build the LLM prompt from the unresolved record and candidate context."""
    order_id = row.get("order_id", "UNKNOWN")
    order_amount = row.get("order_amount", "N/A")
    order_date = row.get("order_date", "N/A")
    customer_id = row.get("customer_id", "N/A")
    order_status = row.get("order_status", "N/A")
    pay_status = row.get("pay_payment_status", "N/A")
    total_refund = row.get("total_refund_amount", 0)

    candidates_text = ""
    if candidates:
        lines = []
        for c in candidates:
            lines.append(
                f"  - {c['source'].upper()} {c['id']}: "
                f"amount ₹{c['amount']}, date {c['date']}"
            )
        candidates_text = "Nearby candidates:\n" + "\n".join(lines)
    else:
        candidates_text = "Nearby candidates: None found within search window."

    return f"""Unresolved transaction record:
  Order ID:       {order_id}
  Order Amount:   ₹{order_amount}
  Order Date:     {order_date}
  Customer ID:    {customer_id}
  Order Status:   {order_status}
  Payment Status: {pay_status}
  Total Refunds:  ₹{total_refund}

{candidates_text}

This record failed exact match, attribute match, fuzzy match, and arithmetic verification.
Please explain (in under 3 sentences) why this record might not have reconciled, referencing any candidates by ID if relevant.
If you cannot determine a reason, respond with exactly: cannot determine"""


def _call_gemini(prompt: str) -> dict:
    """Call Google Gemini 1.5 Flash API."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name="gemini-3.6-flash",
            system_instruction=SYSTEM_PROMPT,
        )
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                max_output_tokens=200,
                temperature=0.1,
            ),
        )
        text = response.text.strip()
        return {"success": True, "explanation": text, "error": None}

    except Exception as e:
        return {
            "success": False,
            "explanation": None,
            "error": f"Gemini API error: {type(e).__name__}: {e}",
        }


def _call_openai(prompt: str) -> dict:
    """Call OpenAI GPT-4o-mini API as fallback."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY, timeout=LLM_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        return {"success": True, "explanation": text, "error": None}

    except Exception as e:
        return {
            "success": False,
            "explanation": None,
            "error": f"OpenAI API error: {type(e).__name__}: {e}",
        }


def _empty_frame(reference_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=reference_df.columns)
