# Stage 05: BigQuery FinOps ROI & Empirical Calibration Audit

Streams real decision and escalation telemetry into a **partitioned and clustered Google Cloud BigQuery table** (`decisions_gateway_telemetry.decision_events`) to audit **empirical probability calibration** and quantify **System 1 vs. System 2 FinOps savings**.

---

## 🛠️ Step-by-Step Instructions

### 1. Ensure Dataset & Partitioned Table Exist
(Automatically created if you already ran `./scripts/setup_gcp.sh`):
```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

bq --location=US --project_id="${GOOGLE_CLOUD_PROJECT}" mk --dataset "${GOOGLE_CLOUD_PROJECT}:decisions_gateway_telemetry" 2>/dev/null || true
bq query --project_id="${GOOGLE_CLOUD_PROJECT}" --use_legacy_sql=false < 05-bigquery-finops/bigquery_schema.sql
```

### 2. Run the Live Labeled Benchmark & Stream Telemetry into BigQuery
```bash
.venv/bin/python 05-bigquery-finops/seed_and_analyze.py
```

### 3. Run Individual FinOps & Calibration Queries via `bq query`
```bash
# Query A: Route Performance & Cost per 1,000,000 Requests
bq query --project_id="${GOOGLE_CLOUD_PROJECT}" --use_legacy_sql=false --format=prettyjson "
SELECT
  stage,
  route_taken,
  COUNT(*) AS requests,
  ROUND(AVG(decision_latency_ms), 2) AS avg_s1_latency_ms,
  ROUND(AVG(reasoning_latency_ms), 2) AS avg_s2_latency_ms,
  ROUND(AVG(overall_latency_ms), 2) AS avg_total_latency_ms,
  SUM(decision_output_tokens) AS total_s1_output_tokens,
  ROUND(AVG(total_cost_usd) * 1000000, 2) AS cost_per_million_reqs_usd
FROM \`${GOOGLE_CLOUD_PROJECT}.decisions_gateway_telemetry.decision_events\`
GROUP BY stage, route_taken
ORDER BY stage, route_taken
"

# Query B: Empirical Calibration Reliability Curve
bq query --project_id="${GOOGLE_CLOUD_PROJECT}" --use_legacy_sql=false --format=prettyjson "
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
FROM \`${GOOGLE_CLOUD_PROJECT}.decisions_gateway_telemetry.decision_events\`
WHERE ground_truth_match IS NOT NULL
GROUP BY confidence_bucket
ORDER BY confidence_bucket DESC
"
```

---

## 🌟 Live BigQuery Analytical Verdicts

### 1. Cloud Run Gateway Route Economics (`stage02_hybrid_gateway`)
```json
[
  {
    "stage": "stage02_hybrid_gateway",
    "route_taken": "FAST_PATH_DECISIONS",
    "requests": "3",
    "avg_s1_latency_ms": "172.58",
    "avg_s2_latency_ms": "0.0",
    "avg_total_latency_ms": "172.66",
    "total_s1_output_tokens": "0",
    "cost_per_million_reqs_usd": "51.6"
  },
  {
    "stage": "stage02_hybrid_gateway",
    "route_taken": "SLOW_PATH_AGENT_PLATFORM",
    "requests": "3",
    "avg_s1_latency_ms": "838.7",
    "avg_s2_latency_ms": "6267.33",
    "avg_total_latency_ms": "7204.42",
    "total_s1_output_tokens": "0",
    "cost_per_million_reqs_usd": "675.33"
  }
]
```

### 2. Empirical Calibration Audit (`stage05_calibration_audit`)
```json
[
  {
    "confidence_bucket": "0.95 - 1.00",
    "evaluated_samples": "10",
    "mean_predicted_confidence": "0.9973",
    "empirical_accuracy": "1.0",
    "abs_calibration_gap": "0.0027"
  }
]
```
