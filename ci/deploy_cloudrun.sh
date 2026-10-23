#!/usr/bin/env bash
set -euo pipefail
: "${API_IMAGE:?}" "${WEB_IMAGE:?}" "${GCP_PROJECT_ID:?}" "${GCP_REGION:?}"
: "${CLOUD_SQL_CONNECTION_NAME:?}" "${CI_COMMIT_SHA:?}"
: "${RUNTIME_CONFIG_VERSION:?Pin a reviewed configuration version}" "${INGEST_CONFIG_VERSION:?Pin a reviewed configuration version}"
RUNTIME="pg-runtime-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
INGEST="pg-ingest-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
WEB="pg-web-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
PREFIX="projects/$GCP_PROJECT_ID/secrets"
gcloud run jobs deploy pharmaguard-migrate --image="$API_IMAGE" --region="$GCP_REGION" \
  --service-account="$INGEST" --set-cloudsql-instances="$CLOUD_SQL_CONNECTION_NAME" \
  --set-env-vars="APP_CONFIG_SECRET=$PREFIX/pg-config-ingest/versions/$INGEST_CONFIG_VERSION" \
  --command=alembic --args=upgrade,head --max-retries=0 --task-timeout=600s --quiet
gcloud run jobs execute pharmaguard-migrate --region="$GCP_REGION" --wait --quiet
gcloud run deploy pharmaguard-api --image="$API_IMAGE" --region="$GCP_REGION" \
  --service-account="$RUNTIME" --add-cloudsql-instances="$CLOUD_SQL_CONNECTION_NAME" \
  --cpu=2 --memory=4Gi --concurrency=1 --min=0 --max=3 --timeout=90 \
  --set-env-vars="APP_CONFIG_SECRET=$PREFIX/pg-config-runtime/versions/$RUNTIME_CONFIG_VERSION,GIT_SHA=$CI_COMMIT_SHA,OMP_NUM_THREADS=2,MKL_NUM_THREADS=2,HF_HUB_OFFLINE=1" --quiet
API_URL=$(gcloud run services describe pharmaguard-api --region="$GCP_REGION" --format='value(status.url)')
gcloud run deploy pharmaguard-web --image="$WEB_IMAGE" --region="$GCP_REGION" \
  --service-account="$WEB" --cpu=1 --memory=512Mi --min=0 --max=3 --timeout=120 \
  --set-env-vars="API_INTERNAL_URL=$API_URL,API_AUTH_MODE=cloudrun" --quiet
WEB_URL=$(gcloud run services describe pharmaguard-web --region="$GCP_REGION" --format='value(status.url)')
printf 'API_URL=%s\nWEB_URL=%s\n' "$API_URL" "$WEB_URL" > deployment.env
gcloud run services describe pharmaguard-api --region="$GCP_REGION" --format=json > api-deployment.json
gcloud run services describe pharmaguard-web --region="$GCP_REGION" --format=json > web-deployment.json
python ci/check_digest.py
