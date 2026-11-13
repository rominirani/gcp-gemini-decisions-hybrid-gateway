#!/usr/bin/env bash
# ==============================================================================
# Deploy Stage 01: Standalone Gemini Decisions API Classifier to Cloud Run
# ==============================================================================
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-us-central1}"
SERVICE_NAME="decisions-classifier"
SA_EMAIL="${SERVICE_ACCOUNT:-decisions-gateway-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "❌ Error: Project ID not specified."
  echo "Usage: ./deploy.sh <PROJECT_ID> [REGION]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Deploying Stage 01 (${SERVICE_NAME}) to Google Cloud Run..."
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"

gcloud run deploy "${SERVICE_NAME}" \
  --source="${SCRIPT_DIR}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${SA_EMAIL}" \
  --allow-unauthenticated \
  --set-env-vars="GEMINI_DECISION_MODEL=gemini-decision-1" \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest" \
  --min-instances=0 \
  --max-instances=5 \
  --memory="512Mi" \
  --cpu="1" \
  --timeout=30s \
  --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")
echo ""
echo "✅ Stage 01 Service is live!"
echo "URL: ${SERVICE_URL}"
