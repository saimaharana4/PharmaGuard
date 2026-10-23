#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?}" "${GCP_ZONE:?}" "${API_IMAGE:?}" "${WEB_IMAGE:?}"
: "${SQL_PROXY_IMAGE:?}" "${RUNTIME_CONFIG_REFERENCE:?}" "${CLOUD_SQL_CONNECTION_NAME:?}"
: "${CI_COMMIT_SHA:?}" "${VM_EXPIRES_AT:?}"
mkdir -p deployment
python3 -m ci.vm_manifest deployment/release.json
python3 -m ci.protect_production before
scope=(--project="$GCP_PROJECT_ID" --zone="$GCP_ZONE" --tunnel-through-iap --quiet)
gcloud compute scp deployment/release.json pharmaguard-hackathon:pg-release.json "${scope[@]}"
gcloud compute scp infra/vm/release.py pharmaguard-hackathon:pg-release-controller.py "${scope[@]}"
gcloud compute ssh pharmaguard-hackathon "${scope[@]}" --command='sudo install -m 0700 ~/pg-release-controller.py /opt/pharmaguard/release.py && sudo install -m 0600 ~/pg-release.json /opt/pharmaguard/candidate.json && sudo python3 /opt/pharmaguard/release.py /opt/pharmaguard/candidate.json && sudo install -m 0600 /opt/pharmaguard/candidate.json /opt/pharmaguard/release.json' | tee deployment/vm-events.jsonl
python3 -m ci.protect_production after
# Collect only the sanitized deployment stream, never docker inspect/env/secret responses.
gcloud compute ssh pharmaguard-hackathon "${scope[@]}" --command='sudo cat /opt/pharmaguard/deployment.jsonl' > deployment/vm-history.jsonl
