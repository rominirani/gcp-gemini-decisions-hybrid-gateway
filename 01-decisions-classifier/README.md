# Stage 01: Standalone Gemini Decisions API Microservice on Cloud Run

This service packages **Google DeepMind's Gemini Decisions API** (`gemini-decision-1` via `google-genai >= 3.2.0`) into a lean, production-hardened **Google Cloud Run** microservice backed by **Google Cloud Secret Manager**.

---

## 🌟 What This Demonstrates
* Evaluating **three decision primitives in one parallel forward pass**:
  * `choice` (`department`): Normalized probability distribution across 6 queues.
  * `noul` (`can_auto_resolve`): Calibrated yes/no probability (`0.01` to `0.99`) gating autonomous webhook execution.
  * `score` (`urgency`): Probability-weighted severity rubric (`0` to `3`).
* **164–243 ms warm end-to-end Cloud Run latency** in `us-central1` using a persistent `genai.Client` HTTP connection pool.
* **Zero output tokens billed** (`$0.10` per 1M input tokens, `$0.00` output tokens).

---

## 🛠️ Deploying to Your Google Cloud Project

```bash
# 1. Store your Google AI Studio API key in Cloud Secret Manager
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key \
  --replication-policy="automatic" \
  --project="YOUR_PROJECT_ID" \
  --data-file=-

# 2. Deploy Stage 01 to Cloud Run
./deploy.sh YOUR_PROJECT_ID us-central1
```

---

## ✅ Live Cloud Run Verification Verdicts

### Test 1: Routine Order Tracking (`185.81 ms`, Auto-Resolvable)
```bash
curl -s -X POST "${SERVICE_URL}/classify" \
  -H "Content-Type: application/json" \
  -d '{"query": "Where is my order #19028? Can you tell me when it arrives?"}'
```
```json
{
  "query": "Where is my order #19028? Can you tell me when it arrives?",
  "model": "gemini-decision-1",
  "department": "order_status",
  "department_confidence": 0.9995,
  "department_probabilities": {
    "account_access": 0.0001,
    "order_status": 0.9995,
    "other": 0.0001,
    "billing_refund": 0.0001,
    "subscription_cancel": 0.0,
    "complex_incident": 0.0002
  },
  "can_auto_resolve": true,
  "auto_resolve_probability": 0.98,
  "urgency_level": "LOW",
  "urgency_score": 0.1524,
  "urgency_confidence": 0.8717,
  "suggested_action": "DISPATCH_ORDER_TRACKING",
  "input_tokens": 424,
  "output_tokens": 0,
  "estimated_cost_usd": 4.24e-05,
  "latency_ms": 185.81,
  "platform": "Google Cloud Run"
}
```

### Test 2: High-Value Duplicate Charge (`173.41 ms`, Calibrated Caution)
```bash
curl -s -X POST "${SERVICE_URL}/classify" \
  -H "Content-Type: application/json" \
  -d '{"query": "I was billed twice on invoice INV-9902 for $140. Please refund the duplicate charge."}'
```
```json
{
  "query": "I was billed twice on invoice INV-9902 for $140. Please refund the duplicate charge.",
  "model": "gemini-decision-1",
  "department": "billing_refund",
  "department_confidence": 0.999,
  "department_probabilities": {
    "order_status": 0.0001,
    "billing_refund": 0.999,
    "other": 0.0003,
    "complex_incident": 0.0001,
    "subscription_cancel": 0.0002,
    "account_access": 0.0002
  },
  "can_auto_resolve": false,
  "auto_resolve_probability": 0.6152,
  "urgency_level": "MEDIUM",
  "urgency_score": 1.2802,
  "urgency_confidence": 0.6646,
  "suggested_action": "INITIATE_BILLING_WORKFLOW",
  "input_tokens": 429,
  "output_tokens": 0,
  "estimated_cost_usd": 4.29e-05,
  "latency_ms": 173.41,
  "platform": "Google Cloud Run"
}
```
> **Why this matters:** While `department` is unambiguously `billing_refund` (`0.999`), `auto_resolve_probability` drops to `0.6152` (below our `0.80` payout threshold), preventing blind automated refunds on a $140 billing dispute!

### Test 3: Production Database Outage (`164.08 ms`, Escalation Trigger)
```bash
curl -s -X POST "${SERVICE_URL}/classify" \
  -H "Content-Type: application/json" \
  -d '{"query": "CRITICAL: Checkout database connection pool exhausted with HTTP 500 errors across all regions."}'
```
```json
{
  "query": "CRITICAL: Checkout database connection pool exhausted with HTTP 500 errors across all regions.",
  "model": "gemini-decision-1",
  "department": "complex_incident",
  "department_confidence": 0.9991,
  "department_probabilities": {
    "complex_incident": 0.9991,
    "account_access": 0.0002,
    "billing_refund": 0.0003,
    "subscription_cancel": 0.0,
    "other": 0.0003,
    "order_status": 0.0001
  },
  "can_auto_resolve": false,
  "auto_resolve_probability": 0.01,
  "urgency_level": "CRITICAL",
  "urgency_score": 2.9723,
  "urgency_confidence": 0.9734,
  "suggested_action": "ESCALATE_TO_SYSTEM2_REASONING",
  "input_tokens": 424,
  "output_tokens": 0,
  "estimated_cost_usd": 4.24e-05,
  "latency_ms": 164.08,
  "platform": "Google Cloud Run"
}
```
