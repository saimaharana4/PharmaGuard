#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?}"
RUNTIME="pg-runtime-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
INGEST="pg-ingest-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
gcloud services enable aiplatform.googleapis.com run.googleapis.com secretmanager.googleapis.com \
  --project="$GCP_PROJECT_ID"
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:$RUNTIME" --role=roles/aiplatform.user --condition=None
for sa in "$RUNTIME" "$INGEST"; do
  gcloud secrets add-iam-policy-binding pg-qdrant-api-key --project="$GCP_PROJECT_ID" \
    --member="serviceAccount:$sa" --role=roles/secretmanager.secretAccessor
done
# Invoke once after first staging deployment, as the project owner. The CI deploy
# identity intentionally lacks permission to change public-access policies.
if [[ "${ENABLE_PUBLIC_DEMO:-false}" == true ]]; then
  gcloud run services add-iam-policy-binding pharmaguard-web --region="${GCP_REGION:-asia-south1}" \
    --project="$GCP_PROJECT_ID" --member=allUsers --role=roles/run.invoker
  gcloud run services add-iam-policy-binding pharmaguard-api --region="${GCP_REGION:-asia-south1}" \
    --project="$GCP_PROJECT_ID" --member="serviceAccount:pg-web-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role=roles/run.invoker
fi
