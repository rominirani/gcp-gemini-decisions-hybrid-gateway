#!/usr/bin/env python3
"""Stage 05: Live BigQuery FinOps & Calibration Audit Runner.

Evaluates a labeled benchmark suite against Gemini Decision 1 (and Gemini 3.8 Flash
for Slow-Path escalations), streams telemetry into BigQuery, and runs parameterized
analytical SQL queries to compute empirical calibration and FinOps ROI.
"""

from datetime import datetime, timezone
import json
import os
import time
import uuid
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DECISION_MODEL = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")
REASONING_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
DATASET_ID = os.getenv("BIGQUERY_DATASET", "decisions_gateway_telemetry")
TABLE_ID = os.getenv("BIGQUERY_TABLE", "decision_events")

LABELED_BENCHMARK = [
    {"query": "Where is my order #19028? Can you tell me when it arrives?", "expected": "order_status"},
    {"query": "Has shipment TRK-88210 cleared customs yet?", "expected": "order_status"},
    {"query": "Please cancel my monthly subscription before renewal.", "expected": "subscription_cancel"},
    {"query": "Stop recurring billing and close my Pro plan at period end.", "expected": "subscription_cancel"},
    {"query": "I forgot my password and my 2FA code expired.", "expected": "account_access"},
    {"query": "Locked out of SSO login after phone replacement—need MFA reset.", "expected": "account_access"},
    {"query": "I was charged twice on invoice INV-4410 for $29. Please refund.", "expected": "billing_refund"},
    {"query": "Duplicate charge of $19 on my statement for order #3102.", "expected": "billing_refund"},
    {"query": "CRITICAL: Checkout DB connection pool exhausted with HTTP 500s.", "expected": "complex_incident"},
    {"query": "Does section 4.2 of our DPA permit EU-to-US BigQuery replication?", "expected": "complex_incident"},
]

QUESTIONS = {
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
    },
    "urgency": {
        "type": "score",
        "instructions": "Rate the operational urgency of this message.",
        "criteria": ["Low", "Medium", "High", "Critical"],
    },
}


def run_audit() -> None:
    if not PROJECT_ID or not GEMINI_API_KEY:
        raise RuntimeError("Both GOOGLE_CLOUD_PROJECT and GEMINI_API_KEY must be set.")

    d_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1beta"})
    r_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
    bq_client = bigquery.Client(project=PROJECT_ID)
    full_table = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    rows_to_stream = []
    batch_tag = f"audit_{int(time.time())}"

    for item in LABELED_BENCHMARK:
        t0 = time.perf_counter()
        res = d_client.decisions.create(
            model=DECISION_MODEL,
            input=item["query"],
            questions=QUESTIONS,
        )
        s1_ms = (time.perf_counter() - t0) * 1000

        dept = res.answers["department"]
        auto = res.answers["can_auto_resolve"]
        s1_in = int(res.usage.total_input_tokens or 0)
        s1_cost = (s1_in / 1_000_000) * 0.10

        is_fast = (
            dept.confidence >= 0.85
            and auto.noul >= 0.80
            and dept.choice not in ("complex_incident", "other")
        )

        s2_in, s2_out, s2_ms, s2_cost = 0, 0, 0.0, 0.0
        route = "FAST_PATH_DECISIONS"
        if not is_fast:
            route = "SLOW_PATH_AGENT_PLATFORM"
            t1 = time.perf_counter()
            s2_resp = r_client.models.generate_content(
                model=REASONING_MODEL,
                contents=f"Provide JSON {{\"action\": \"...\", \"summary\": \"...\"}} for: {item['query']}",
                config=types.GenerateContentConfig(
                    temperature=0.2, response_mime_type="application/json"
                ),
            )
            s2_ms = (time.perf_counter() - t1) * 1000
            s2_in = int((s2_resp.usage_metadata.prompt_token_count if s2_resp.usage_metadata else 0) or 0)
            s2_out = int((s2_resp.usage_metadata.candidates_token_count if s2_resp.usage_metadata else 0) or 0)
            s2_cost = (s2_in / 1_000_000 * 0.30) + (s2_out / 1_000_000 * 2.50)

        rows_to_stream.append(
            {
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": f"{batch_tag}_{uuid.uuid4().hex[:8]}",
                "stage": "stage05_calibration_audit",
                "route_taken": route,
                "question_count": 3,
                "modalities": "text",
                "decision_input_tokens": s1_in,
                "decision_output_tokens": 0,
                "reasoning_input_tokens": s2_in,
                "reasoning_output_tokens": s2_out,
                "decision_latency_ms": round(s1_ms, 2),
                "reasoning_latency_ms": round(s2_ms, 2),
                "overall_latency_ms": round(s1_ms + s2_ms, 2),
                "total_cost_usd": round(s1_cost + s2_cost, 7),
                "top_choice": dept.choice,
                "confidence": round(dept.confidence, 4),
                "auto_resolve_prob": round(auto.noul, 4),
                "ground_truth_match": bool(dept.choice == item["expected"]),
            }
        )

    errors = bq_client.insert_rows_json(full_table, rows_to_stream)
    if errors:
        raise RuntimeError(f"BigQuery streaming insert errors: {errors}")

    # Parameterized analytical queries against BigQuery
    finops_sql = f"""
    SELECT
      route_taken,
      COUNT(*) AS requests,
      ROUND(AVG(overall_latency_ms), 2) AS avg_latency_ms,
      SUM(decision_output_tokens) AS s1_output_tokens,
      ROUND(AVG(total_cost_usd) * 1000000, 2) AS cost_per_million_reqs_usd,
      ROUND(AVG(confidence), 4) AS mean_confidence,
      ROUND(AVG(IF(ground_truth_match, 1.0, 0.0)), 4) AS empirical_accuracy
    FROM `{full_table}`
    WHERE stage = @stage_name
    GROUP BY route_taken
    ORDER BY route_taken
    """
    calibration_sql = f"""
    SELECT
      CASE
        WHEN confidence >= 0.95 THEN '0.95 - 1.00'
        WHEN confidence >= 0.85 THEN '0.85 - 0.95'
        WHEN confidence >= 0.70 THEN '0.70 - 0.85'
        ELSE '< 0.70'
      END AS confidence_bucket,
      COUNT(*) AS evaluated_samples,
      ROUND(AVG(confidence), 4) AS mean_predicted_confidence,
      ROUND(AVG(IF(ground_truth_match, 1.0, 0.0)), 4) AS empirical_accuracy,
      ROUND(ABS(AVG(confidence) - AVG(IF(ground_truth_match, 1.0, 0.0))), 4) AS abs_calibration_gap
    FROM `{full_table}`
    WHERE stage = @stage_name AND ground_truth_match IS NOT NULL
    GROUP BY confidence_bucket
    ORDER BY confidence_bucket DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("stage_name", "STRING", "stage05_calibration_audit")
        ],
        labels={"datacloud": "antigravity"},
    )
    finops_rows = [dict(row) for row in bq_client.query(finops_sql, job_config=job_config).result()]
    cal_rows = [dict(row) for row in bq_client.query(calibration_sql, job_config=job_config).result()]
    print(
        json.dumps(
            {
                "inserted_rows": len(rows_to_stream),
                "route_finops_summary": finops_rows,
                "calibration_audit": cal_rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    run_audit()
