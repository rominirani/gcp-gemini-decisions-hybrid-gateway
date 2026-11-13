#!/usr/bin/env python3
"""Standalone Quickstart: Calling the Gemini Decisions API (gemini-decision-1).

Evaluates three typed questions (noul, choice, score) in a single forward pass
with calibrated probabilities and 0 output tokens billed.
Requires GEMINI_API_KEY in the environment (or local .env file). No fallbacks.
"""

import json
import os
import sys
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

DECISION_MODEL = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")

ACTION_MAP = {
    "order_status": "DISPATCH_TRACKING_WEBHOOK",
    "billing_refund": "INITIATE_BILLING_WORKFLOW",
    "account_access": "SEND_VERIFIED_MFA_RESET",
    "subscription_cancel": "RUN_RETENTION_CANCELLATION_FLOW",
    "complex_incident": "ESCALATE_TO_SYSTEM2_REASONING",
    "other": "ESCALATE_TO_HUMAN_REVIEW",
}


def classify_inquiry(query_text: str) -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required. Export GEMINI_API_KEY from Google AI Studio "
            "(https://aistudio.google.com/api-keys) before running this script."
        )

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    start = time.perf_counter()
    result = client.decisions.create(
        model=DECISION_MODEL,
        input=query_text,
        questions={
            "department": {
                "type": "choice",
                "instructions": "Which operational queue should handle this customer message?",
                "criteria": {
                    "order_status": "Order tracking, delivery dates, or shipment status.",
                    "billing_refund": "Duplicate charges, invoices, credits, or refund requests.",
                    "subscription_cancel": "Canceling or pausing a recurring subscription.",
                    "account_access": "Password resets, expired 2FA/MFA codes, or login lockouts.",
                    "complex_incident": "Production outages, HTTP 500 errors, architecture, or legal/DPA questions.",
                    "other": "Anything outside these specific categories.",
                },
            },
            "can_auto_resolve": {
                "type": "noul",
                "instructions": "Can this request be fulfilled deterministically by an automated backend lookup or webhook without custom investigation?",
                "criteria": {
                    "true_description": "Routine single-intent request such as checking tracking, resetting login, or standard cancellation.",
                    "false_description": "Production outage, multi-part legal question, ambiguous dispute, or engineering troubleshooting.",
                },
            },
            "urgency": {
                "type": "score",
                "instructions": "Rate the operational urgency and severity of this message.",
                "criteria": [
                    "Low: Routine informational or tracking question.",
                    "Medium: Standard account, subscription, or billing request.",
                    "High: Time-sensitive customer impact or repeated billing failure.",
                    "Critical: Production-halting outage, data loss risk, or security incident.",
                ],
            },
        },
    )
    latency_ms = (time.perf_counter() - start) * 1000

    dept = result.answers["department"]
    auto = result.answers["can_auto_resolve"]
    urg = result.answers["urgency"]
    top_urg_idx = max(urg.probabilities, key=urg.probabilities.get)

    summary = {
        "query": query_text,
        "model": DECISION_MODEL,
        "latency_ms": round(latency_ms, 2),
        "department": {
            "choice": dept.choice,
            "confidence": round(dept.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in dept.probabilities.items()},
        },
        "can_auto_resolve": {
            "noul_probability_yes": round(auto.noul, 4),
            "confidence": round(auto.confidence, 4),
            "decision": auto.noul >= 0.80,
        },
        "urgency": {
            "expected_score_0_to_3": round(urg.score, 4),
            "top_level": urg.legend[top_urg_idx],
            "confidence": round(urg.confidence, 4),
        },
        "suggested_action": ACTION_MAP.get(dept.choice, "ESCALATE_TO_HUMAN_REVIEW"),
        "usage": {
            "total_input_tokens": result.usage.total_input_tokens,
            "total_output_tokens": result.usage.total_output_tokens,
            "estimated_cost_usd": round((result.usage.total_input_tokens / 1_000_000) * 0.10, 7),
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sample_query = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "Where is my order #19028? Can you tell me when it arrives?"
    )
    classify_inquiry(sample_query)
