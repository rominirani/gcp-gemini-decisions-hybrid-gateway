#!/usr/bin/env bash
# ==============================================================================
# Google Cloud Infrastructure Setup for Gemini Decisions API 5-Part Series
# ==============================================================================
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-us-central1}"
GEMINI_KEY_INPUT="${3:-${GEMINI_API_KEY:-}}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "❌ Error: Project ID not provided."
  echo "Usage: ./scripts/setup_gcp.sh <PROJECT_ID> [REGION] [GEMINI_API_KEY]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "🚀 Configuring Google Cloud project: ${PROJECT_ID} in ${REGION}"

echo "📦 1. Enabling required Google Cloud APIs..."
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  generativelanguage.googleapis.com \
  secretmanager.googleapis.com \
  pubsub.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet

echo "🔐 2. Configuring GEMINI_API_KEY in Cloud Secret Manager..."
if ! gcloud secrets describe gemini-api-key --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud secrets create gemini-api-key \
    --replication-policy="automatic" \
    --project="${PROJECT_ID}" \
    --quiet
  echo "✅ Created secret 'gemini-api-key'."
else
  echo "ℹ️ Secret 'gemini-api-key' already exists."
fi

if [[ -n "${GEMINI_KEY_INPUT}" ]]; then
  printf "%s" "${GEMINI_KEY_INPUT}" | gcloud secrets versions add gemini-api-key \
    --data-file=- \
    --project="${PROJECT_ID}" \
    --quiet
  echo "✅ Added latest secret version for 'gemini-api-key'."
else
  echo "⚠️ No GEMINI_API_KEY passed yet. Before deploying Cloud Run services, add a version:"
  echo "   printf '%s' 'YOUR_GEMINI_API_KEY' | gcloud secrets versions add gemini-api-key --data-file=- --project=${PROJECT_ID}"
fi

echo "👤 3. Creating dedicated Least-Privilege Service Account..."
SA_NAME="decisions-gateway-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Gemini Decisions Hybrid Gateway Cloud Run SA" \
    --project="${PROJECT_ID}" \
    --quiet
  echo "✅ Created service account: ${SA_EMAIL} (waiting 10s for IAM propagation...)"
  sleep 10
else
  echo "ℹ️ Service account '${SA_EMAIL}' already exists."
fi

echo "🛡️ 4. Binding Least-Privilege IAM Roles..."
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}" \
  --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --condition=None \
  --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataEditor" \
  --condition=None \
  --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None \
  --quiet

echo "📊 5. Initializing BigQuery Telemetry Dataset & Partitioned Table..."
if ! bq --project_id="${PROJECT_ID}" show "${PROJECT_ID}:decisions_gateway_telemetry" >/dev/null 2>&1; then
  bq --location=US --project_id="${PROJECT_ID}" mk --dataset "${PROJECT_ID}:decisions_gateway_telemetry"
fi
bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false < "${REPO_ROOT}/05-bigquery-finops/bigquery_schema.sql"

echo ""
echo "🎉 Setup Complete!"
echo "Service Account: ${SA_EMAIL}"
echo "Next steps — deploy individual stages from ${REPO_ROOT}:"
echo "  ./01-decisions-classifier/deploy.sh ${PROJECT_ID} ${REGION}"
echo "  ./02-hybrid-gateway/deploy.sh ${PROJECT_ID} ${REGION}"
echo "  ./03-multimodal-triage/deploy.sh ${PROJECT_ID} ${REGION}"
echo "  ./04-pubsub-policy-stream/deploy.sh ${PROJECT_ID} ${REGION}"
