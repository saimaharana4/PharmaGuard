#!/usr/bin/env bash
set -euo pipefail
: "${EDGE_IMAGE:?}" "${GCP_PROJECT_ID:?}" "${GCP_REGION:?}"
[[ "$EDGE_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]] || exit 1
# Owner bootstrap makes this staging service public once. CI preserves its IAM policy.
gcloud run deploy pharmaguard-vm-preview --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --image="$EDGE_IMAGE" --service-account="pg-web-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --network=pg-hackathon --subnet=pg-preview --network-tags=pg-preview --vpc-egress=private-ranges-only \
  --set-env-vars=UPSTREAM_URL=http://10.73.0.2:8081 --cpu=1 --memory=256Mi --min=0 --max=2 \
  --timeout=120 --quiet
# A prior pinned preview revision must not keep routing to the production listener.
gcloud run services update-traffic pharmaguard-vm-preview --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --to-latest --quiet
