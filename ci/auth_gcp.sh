#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_WIF_PROVIDER:?Set the full Workload Identity provider resource name}"
: "${GCP_DEPLOY_SERVICE_ACCOUNT:?Set deployment service account email}"
: "${GCP_ID_TOKEN:?GitLab OIDC id_token is required}"
umask 077
AUTH_DIR=$(mktemp -d)
printf '%s' "$GCP_ID_TOKEN" > "$AUTH_DIR/token"
gcloud iam workload-identity-pools create-cred-config "$GCP_WIF_PROVIDER" \
  --service-account="$GCP_DEPLOY_SERVICE_ACCOUNT" \
  --credential-source-file="$AUTH_DIR/token" --output-file="$AUTH_DIR/credentials.json" >/dev/null
export GOOGLE_APPLICATION_CREDENTIALS="$AUTH_DIR/credentials.json"
gcloud auth login --cred-file="$GOOGLE_APPLICATION_CREDENTIALS" --brief --quiet
gcloud config set project "$GCP_PROJECT_ID" --quiet
# This file is sourced; the caller removes AUTH_DIR on exit.
