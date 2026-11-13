# Stage 02: Hybrid System 1 / System 2 AI Gateway on Google Cloud Run

Combines **Gemini Decision 1** (`gemini-decision-1` via the Gemini Decisions API, **0 output tokens**) as a sub-200ms **System 1 control plane** with **Gemini 3.8 Flash on Google Cloud's Gemini Enterprise Agent Platform** (`gemini-3.8-flash` via keyless IAM Application Default Credentials) for **System 2 deep reasoning**—complete with a CSP-hardened interactive **Latency Waterfall Dashboard**.

---

## 🛠️ Step-by-Step Deployment & Testing Instructions

### 1. Prerequisites
Ensure you have run `./scripts/setup_gcp.sh YOUR_PROJECT_ID us-central1 YOUR_GEMINI_API_KEY` from the repository root so `gemini-api-key`, `decisions-gateway-sa`, and the BigQuery dataset exist.

### 2. Deploy Stage 02 to Cloud Run
```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"

./02-hybrid-gateway/deploy.sh "${PROJECT_ID}" "${REGION}"

export STAGE02_URL=$(gcloud run services describe decisions-hybrid-gateway \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")
echo "Stage 02 URL: ${STAGE02_URL}"
```

### 3. Open the Interactive Latency Waterfall UI
Open `${STAGE02_URL}` in your browser, click any `[Fast Path]` or `[Slow Path]` preset button, and click **Evaluate & Route**.

### 4. Test via CLI (`curl`)

> **Note:** Because `min-instances=0` scales idle containers to zero, your very first request warms the TLS connection pool; run a Fast-Path command a second time to observe steady-state `155–192 ms` latency.

```bash
# Health check
curl -s "${STAGE02_URL}/health" | python3 -m json.tool

# Test A — Fast Path (System 1 only, ~155–192 ms, 0 output tokens)
curl -s -X POST "${STAGE02_URL}/api/v1/triage" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Please cancel my monthly subscription before the next billing cycle.",
    "customer_tier": "STANDARD"
  }' | python3 -m json.tool

# Test B — Slow Path Escalation (System 1 flags P(auto_resolve)=0.01 -> System 2 Gemini 3.8 Flash)
curl -s -X POST "${STAGE02_URL}/api/v1/triage" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "CRITICAL: Checkout database connection pool exhausted, returning HTTP 500 errors across all regions after schema migration.",
    "customer_tier": "ENTERPRISE"
  }' | python3 -m json.tool
```

---

## 🌟 Measured Cloud Run Performance (`us-central1`)

| Inquiry Type | Route Taken | System 1 Latency | System 2 Latency | Total Latency | Total Cost |
| :--- | :--- | :---: | :---: | :---: | :---: |
| Order Tracking (`#19028`) | `FAST_PATH_DECISIONS` | `192.11 ms` | `0 ms (Bypassed)` | **`192.21 ms`** | **`$0.0000518`** |
| Subscription Cancel | `FAST_PATH_DECISIONS` | `155.67 ms` | `0 ms (Bypassed)` | **`155.75 ms`** | **`$0.0000510`** |
| MFA / 2FA Recovery | `FAST_PATH_DECISIONS` | `169.96 ms` | `0 ms (Bypassed)` | **`170.03 ms`** | **`$0.0000520`** |
| Multi-Region DB Outage | `SLOW_PATH_AGENT_PLATFORM` | `168.69 ms` | `6,001.79 ms` | `6,170.67 ms` | `$0.0006960` |
| Cross-Border EU DPA Legal | `SLOW_PATH_AGENT_PLATFORM` | `201.54 ms` | `6,164.26 ms` | `6,366.00 ms` | `$0.0008980` |
