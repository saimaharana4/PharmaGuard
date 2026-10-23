#!/usr/bin/env bash
set -euo pipefail
: "${EDGE_IMAGE:?}" "${GCP_PROJECT_ID:?}" "${GCP_REGION:?}" "${WEB_URL:?}"
: "${GCP_ZONE:?}" "${CI_JOB_ID:?}"
[[ "$EDGE_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]] || exit 1
[[ "$CI_JOB_ID" =~ ^[0-9]+$ ]] || exit 1
python3 -m ci.vm_manifest deployment/promotion-release.json
gcloud run deploy pharmaguard-web --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --image="$EDGE_IMAGE" --service-account="pg-web-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --network=pg-hackathon --subnet=pg-edge --network-tags=pg-edge --vpc-egress=private-ranges-only \
  --set-env-vars=UPSTREAM_URL=http://10.73.0.2:8080 --cpu=1 --memory=256Mi --min=0 --max=3 \
  --timeout=120 --no-traffic --quiet
# A previous rollback pins traffic to its revision across later deployments.
# Verify the new ready revision's digest before moving the approved public route.
revision=$(gcloud run services describe pharmaguard-web --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestCreatedRevisionName)')
[[ "$revision" =~ ^pharmaguard-web-[a-z0-9-]+$ ]] || exit 1
deployed_image=$(gcloud run revisions describe "$revision" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.imageDigest)')
[[ "$deployed_image" == "$EDGE_IMAGE" ]] || exit 1
# A newly created zero-traffic revision can differ from latestReadyRevisionName.
gcloud run revisions describe "$revision" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='json(status.conditions)' | python3 -c '
import json, sys
conditions = json.load(sys.stdin).get("status", {}).get("conditions", [])
if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
    raise SystemExit("Target revision is not ready; public traffic unchanged")
'
gcloud run services update-traffic pharmaguard-web --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --to-revisions="$revision=100" --quiet
# The verified edge still uses the old production pin. Only this human-approved
# job may move that pin, and only if its exact staging manifest remains current.
scope=(--project="$GCP_PROJECT_ID" --zone="$GCP_ZONE" --tunnel-through-iap --quiet)
remote="pg-promote-$CI_JOB_ID.json"
gcloud compute scp deployment/promotion-release.json "pharmaguard-hackathon:$remote" "${scope[@]}"
gcloud compute ssh pharmaguard-hackathon "${scope[@]}" \
  --command="sudo install -m 0600 ~/$remote /opt/pharmaguard/$remote && sudo python3 /opt/pharmaguard/release.py --promote /opt/pharmaguard/$remote && sudo rm -f /opt/pharmaguard/$remote"
# Full reviewed public smoke remains mandatory after traffic promotion.
echo 'Run the reviewed postdeploy smoke and record the previous Cloud Run revision for rollback.'
