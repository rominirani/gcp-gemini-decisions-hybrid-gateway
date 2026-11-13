# Stage 03: Native Multimodal Parcel, Claims & Facility Triage on Cloud Run

Demonstrates **Gemini Decision 1's native multimodal evaluation** across **images** (`image/jpeg`, `image/png`, `image/webp`) and **PDF documents** (`application/pdf`) combined with structured JSON metadata in a **single forward pass** with **0 output tokens**—eliminating standalone OCR and vision pre-processing pipelines.

---

## 🛠️ Step-by-Step Deployment & Testing Instructions

### 1. Deploy Stage 03 to Cloud Run
```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"

./03-multimodal-triage/deploy.sh "${PROJECT_ID}" "${REGION}"

export STAGE03_URL=$(gcloud run services describe decisions-multimodal-triage \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")
echo "Stage 03 URL: ${STAGE03_URL}"
```

### 2. Test 1 & Test 2: Compare `resolution="low"` vs. `resolution="high"` on an Inspection Photo
```bash
# Low resolution (266 image tokens, $0.0000802)
curl -s -X POST "${STAGE03_URL}/triage/uri" \
  -H "Content-Type: application/json" \
  -d '{
    "claim_text": "Breakroom counter check before 9 AM client meeting. Small coffee spill spotted next to wiping cloth.",
    "metadata": {"building": "SFO-2", "room": "4B"},
    "media_block_type": "image",
    "media_uri": "https://storage.googleapis.com/generativeai-downloads/images/spill.jpg",
    "mime_type": "image/jpeg",
    "resolution": "low"
  }' | python3 -m json.tool

# High resolution (1,064 image tokens — 4x more image tokens!)
curl -s -X POST "${STAGE03_URL}/triage/uri" \
  -H "Content-Type: application/json" \
  -d '{
    "claim_text": "Breakroom counter check before 9 AM client meeting. Small coffee spill spotted next to wiping cloth.",
    "metadata": {"building": "SFO-2", "room": "4B"},
    "media_block_type": "image",
    "media_uri": "https://storage.googleapis.com/generativeai-downloads/images/spill.jpg",
    "mime_type": "image/jpeg",
    "resolution": "high"
  }' | python3 -m json.tool
```

### 3. Test 3: Upload the Included Duplicate-Charge PDF Invoice (`sample_invoice_8812.pdf`)
```bash
curl -s -X POST "${STAGE03_URL}/triage/upload" \
  -F 'claim_text=I was double-charged $45 twice ($90 total) on invoice INV-8812. Attached is my PDF invoice.' \
  -F 'customer_tier=PREMIUM' \
  -F 'file=@03-multimodal-triage/sample_invoice_8812.pdf;type=application/pdf' | python3 -m json.tool
```

### 4. Test 4: Verify SSRF Allowlist Defense (`HTTP 400`)
```bash
curl -s -i -X POST "${STAGE03_URL}/triage/uri" \
  -H "Content-Type: application/json" \
  -d '{
    "claim_text": "SSRF test probe",
    "metadata": {},
    "media_block_type": "image",
    "media_uri": "http://169.254.169.254/computeMetadata/v1/",
    "mime_type": "image/jpeg",
    "resolution": "low"
  }'
```

---

## 🌟 Measured Multimodal Cloud Run Verdicts (`us-central1`)

| Test Case | Modality & Setting | Input Tokens (`text` / `image`) | Output Tokens | Latency | Top Disposition (`Confidence`) | Cost |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: |
| Breakroom Spill Photo | `image/jpeg` (`resolution="low"`) | `536` / **`266`** (`802` total) | `0` | **`438.26 ms`** | `local_cleanup_or_self_service` (`94.71%`) | `$0.0000802` |
| Breakroom Spill Photo | `image/jpeg` (`resolution="high"`) | `536` / **`1064`** (`1600` total) | `0` | **`424.79 ms`** | `local_cleanup_or_self_service` (`95.75%`) | `$0.0001600` |
| Duplicate Charge Invoice | `application/pdf` (multipart upload) | `675` / **`520`** (`1195` total) | `0` | **`470.15 ms`** | `automated_credit_or_replacement` (`94.19%`) | `$0.0001195` |
| SSRF Metadata Probe | `http://169.254.169.254/...` | Rejected pre-flight | — | `<2 ms` | `HTTP 400` (Allowlist blocked) | `$0.00` |
