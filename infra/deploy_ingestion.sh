#!/usr/bin/env bash
set -euo pipefail
: "${API_IMAGE:?}" "${GCP_PROJECT_ID:?}" "${CLOUD_SQL_CONNECTION_NAME:?}"
: "${FAERS_RELEASE_MANIFEST:?Reviewed GCS release manifest URI required}"
: "${INGEST_CONFIG_VERSION:=1}"
gcloud run jobs deploy pharmaguard-ingest --region="${GCP_REGION:-asia-south1}" \
  --image="$API_IMAGE" --service-account="pg-ingest-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --set-cloudsql-instances="$CLOUD_SQL_CONNECTION_NAME" --cpu=2 --memory=8Gi \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=86400s \
  --set-env-vars="APP_CONFIG_SECRET=projects/$GCP_PROJECT_ID/secrets/pg-config-ingest/versions/$INGEST_CONFIG_VERSION,FAERS_RELEASE_MANIFEST=$FAERS_RELEASE_MANIFEST,OMP_NUM_THREADS=2,MKL_NUM_THREADS=2,HF_HUB_OFFLINE=1" \
  --command=pharmaguard-ingest --args=run --quiet
