#!/usr/bin/env bash
set -euo pipefail
: "${GCP_REGION:?}" "${GCP_PROJECT_ID:?}" "${ARTIFACT_REPOSITORY:?}" "${CI_COMMIT_SHA:?}"
registry="$GCP_REGION-docker.pkg.dev"
: > images.env
gcloud auth print-access-token | docker login -u oauth2accesstoken --password-stdin "https://$registry"
for app in api web edge; do
  image="$registry/$GCP_PROJECT_ID/$ARTIFACT_REPOSITORY/pharmaguard-$app:$CI_COMMIT_SHA"
  dockerfile="apps/$app/Dockerfile"
  if [[ "$app" == edge ]]; then dockerfile="infra/edge/Dockerfile"; fi
  # Retrying the same pipeline reuses its already-published immutable artifact.
  if ! gcloud artifacts docker images describe "$image" --format='value(image_summary.digest)' >/dev/null 2>&1; then
    docker build --pull -f "$dockerfile" -t "$image" .
    docker push "$image"
  fi
  digest=$(gcloud artifacts docker images describe "$image" --format='value(image_summary.digest)')
  [[ "$digest" == sha256:* ]] || { echo 'Missing immutable image digest' >&2; exit 1; }
  printf '%s_IMAGE=%s@%s\n' "${app^^}" "${image%:*}" "$digest" >> images.env
done
