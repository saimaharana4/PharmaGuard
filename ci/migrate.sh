#!/usr/bin/env bash
set -euo pipefail
: "${API_IMAGE:?}" "${GCP_PROJECT_ID:?}" "${GCP_REGION:?}" "${INGEST_CONFIG_VERSION:?}" "${CLOUD_SQL_CONNECTION_NAME:?}"
gcloud run jobs deploy pharmaguard-migrate --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --image="$API_IMAGE" --service-account="pg-ingest-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --set-cloudsql-instances="$CLOUD_SQL_CONNECTION_NAME" \
  --set-env-vars="APP_CONFIG_SECRET=projects/$GCP_PROJECT_ID/secrets/pg-config-ingest/versions/$INGEST_CONFIG_VERSION" \
  --command=alembic --args=upgrade,head --max-retries=0 --task-timeout=600s --quiet
gcloud run jobs execute pharmaguard-migrate --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --wait --quiet
