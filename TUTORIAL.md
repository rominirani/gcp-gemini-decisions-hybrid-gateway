# Setup & Deployment Guide

Step-by-step commands to run the local Python scripts and deploy the Google Cloud Run and BigQuery examples in this repository.

---

## 1. Local Python Examples (No Cloud Setup Needed)

Requires **Python 3.11+** and a **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/api-keys).

```bash
git clone https://github.com/rominirani/gcp-gemini-decisions-hybrid-gateway.git
cd gcp-gemini-decisions-hybrid-gateway

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

### 1.1 Routing Support Tickets (`scripts/quickstart_decisions.py`)
```bash
# Simple tracking question
python scripts/quickstart_decisions.py

# Unverified $140 duplicate-charge claim
python scripts/quickstart_decisions.py \
  "I was billed twice (\$140 total) on invoice #8812 for one seat. Refund \$70 right now."
```

### 1.2 Running 8 Policy Checks in One Call (`scripts/parallel_guardrails.py`)
```bash
python scripts/parallel_guardrails.py
```

### 1.3 Checking Photos and PDFs Without OCR (`scripts/multimodal_triage.py`)
```bash
python scripts/multimodal_triage.py
```

---

## 2. Deploying on Google Cloud Run + BigQuery

### Step 1: Prepare Your Google Cloud Project (`scripts/setup_gcp.sh`)
```bash
export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export REGION="us-central1"
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

gcloud config set project "${PROJECT_ID}"
./scripts/setup_gcp.sh "${PROJECT_ID}" "${REGION}"
```

### Step 2: Deploy the Cloud Run Router (`02-hybrid-gateway/`)
```bash
./02-hybrid-gateway/deploy.sh "${PROJECT_ID}" "${REGION}"

export SERVICE_URL=$(gcloud run services describe decisions-hybrid-gateway \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")
echo "Service URL: ${SERVICE_URL}"
```

Open `${SERVICE_URL}` in your browser to test the web UI, or test from your terminal:

```bash
# Fast Path (~155–195 ms warm, 0 output tokens)
curl -s -X POST "${SERVICE_URL}/api/v1/triage" \
  -H "Content-Type: application/json" \
  -d '{"query": "Please cancel my monthly subscription before the next billing cycle.", "customer_tier": "STANDARD"}' | python3 -m json.tool

# Escalated Path (hands off to gemini-3.8-flash)
curl -s -X POST "${SERVICE_URL}/api/v1/triage" \
  -H "Content-Type: application/json" \
  -d '{"query": "CRITICAL: Checkout database connection pool exhausted, returning HTTP 500 errors across all regions after schema migration.", "customer_tier": "ENTERPRISE"}' | python3 -m json.tool
```

### Step 3: Run BigQuery Cost & Accuracy Queries (`05-bigquery-finops/`)
```bash
python 05-bigquery-finops/seed_and_analyze.py

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=prettyjson "
SELECT
  route_taken,
  COUNT(*) AS requests,
  ROUND(AVG(overall_latency_ms), 2) AS avg_total_latency_ms,
  SUM(decision_output_tokens) AS total_s1_output_tokens,
  ROUND(AVG(total_cost_usd) * 1000000, 2) AS cost_per_million_reqs_usd
FROM \`${PROJECT_ID}.decisions_gateway_telemetry.decision_events\`
WHERE stage = 'stage02_hybrid_gateway'
GROUP BY route_taken
ORDER BY route_taken
"

bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=prettyjson "
SELECT
  CASE
    WHEN confidence >= 0.95 THEN '0.95 - 1.00'
    WHEN confidence >= 0.85 THEN '0.85 - 0.95'
    ELSE '< 0.85'
  END AS confidence_bucket,
  COUNT(*) AS evaluated_samples,
  ROUND(AVG(confidence), 4) AS mean_predicted_confidence,
  ROUND(AVG(IF(ground_truth_match, 1.0, 0.0)), 4) AS empirical_accuracy,
  ROUND(ABS(AVG(confidence) - AVG(IF(ground_truth_match, 1.0, 0.0))), 4) AS abs_calibration_gap
FROM \`${PROJECT_ID}.decisions_gateway_telemetry.decision_events\`
WHERE ground_truth_match IS NOT NULL
GROUP BY confidence_bucket
ORDER BY confidence_bucket DESC
"
```

---

## 3. Additional Cloud Run Examples

### Standalone Classifier ([`01-decisions-classifier/`](01-decisions-classifier/README.md))
```bash
./01-decisions-classifier/deploy.sh "${PROJECT_ID}" "${REGION}"
```

### Multipart Photo & PDF Upload API ([`03-multimodal-triage/`](03-multimodal-triage/README.md))
```bash
./03-multimodal-triage/deploy.sh "${PROJECT_ID}" "${REGION}"
```

### Cloud Pub/Sub Push Worker ([`04-pubsub-policy-stream/`](04-pubsub-policy-stream/README.md))
```bash
./04-pubsub-policy-stream/deploy.sh "${PROJECT_ID}" "${REGION}"
```

### Google ADK 2.0 Workflows + Decisions API ([`06-adk-workflows/`](06-adk-workflows/README.md))
```bash
cd 06-adk-workflows
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
python benchmark_workflows.py
```

---

## 4. Cleanup

```bash
gcloud pubsub subscriptions delete decisions-triage-push-sub --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud pubsub topics delete decisions-triage-events --project="${PROJECT_ID}" --quiet 2>/dev/null || true

for svc in decisions-hybrid-gateway decisions-classifier decisions-multimodal-triage decisions-pubsub-policy; do
  gcloud run services delete "${svc}" --region="${REGION}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done

bq --project_id="${PROJECT_ID}" rm -r -f -d "${PROJECT_ID}:decisions_gateway_telemetry"
```
