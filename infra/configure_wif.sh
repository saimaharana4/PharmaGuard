#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?}" "${GITLAB_PROJECT_ID:?Numeric project ID required}" "${GITLAB_GROUP_ID:?Numeric group ID required}"
: "${GITLAB_DEFAULT_BRANCH:=main}"
[[ "$GITLAB_PROJECT_ID" =~ ^[0-9]+$ && "$GITLAB_GROUP_ID" =~ ^[0-9]+$ ]] || exit 1
[[ "$GITLAB_DEFAULT_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || exit 1
POOL=pharmaguard-gitlab
PROVIDER=gitlab
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')
SA="pg-gitlab-deploy-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com"
gcloud iam workload-identity-pools describe "$POOL" --location=global --project="$GCP_PROJECT_ID" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" --location=global --project="$GCP_PROJECT_ID"
condition="assertion.namespace_id=='$GITLAB_GROUP_ID' && assertion.project_id=='$GITLAB_PROJECT_ID' && assertion.ref_type=='branch' && assertion.ref=='$GITLAB_DEFAULT_BRANCH' && assertion.ref_protected=='true'"
if gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool="$POOL" --location=global --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --workload-identity-pool="$POOL" --location=global --project="$GCP_PROJECT_ID" --attribute-condition="$condition"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global --project="$GCP_PROJECT_ID" \
    --issuer-uri=https://gitlab.com \
    --attribute-mapping='google.subject=assertion.sub,attribute.project_id=assertion.project_id,attribute.namespace_id=assertion.namespace_id' \
    --attribute-condition="$condition"
fi
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$GCP_PROJECT_ID" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.project_id/$GITLAB_PROJECT_ID" \
  --role=roles/iam.workloadIdentityUser

# Owner bootstrap: metadata reads for Terraform, scoped writes for release operations.
# CI cannot change project IAM, create/delete VMs, or access secret payloads directly.
: "${GCP_REGION:=asia-south1}" "${GCP_ZONE:=asia-south1-a}"
: "${TF_STATE_BUCKET:=pg-tf-state-$PROJECT_NUMBER}"
member="serviceAccount:$SA"
for role in roles/run.developer roles/compute.viewer roles/iam.securityReviewer; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" --member="$member" \
    --role="$role" --condition=None >/dev/null
done
gcloud artifacts repositories add-iam-policy-binding pharmaguard-hackathon \
  --project="$GCP_PROJECT_ID" --location="$GCP_REGION" \
  --member="$member" --role=roles/artifactregistry.writer >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$TF_STATE_BUCKET" \
  --member="$member" --role=roles/storage.objectAdmin >/dev/null
for identity in pg-vm-sa pg-ingest-sa pg-runtime-sa pg-web-sa; do
  gcloud iam service-accounts add-iam-policy-binding \
    "$identity@$GCP_PROJECT_ID.iam.gserviceaccount.com" --project="$GCP_PROJECT_ID" \
    --member="$member" --role=roles/iam.serviceAccountUser >/dev/null
done
gcloud compute instances add-iam-policy-binding pharmaguard-hackathon \
  --project="$GCP_PROJECT_ID" --zone="$GCP_ZONE" \
  --member="$member" --role=roles/compute.osAdminLogin >/dev/null
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" --member="$member" \
  --role=roles/iap.tunnelResourceAccessor \
  --condition="expression=destination.port == 22 && destination.ip == '10.73.0.2',title=pharmaguard-vm-ssh" >/dev/null
permissions=compute.instances.get,compute.instances.setMetadata,compute.instances.setLabels
if gcloud iam roles describe pharmaGuardVmUpdate --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam roles update pharmaGuardVmUpdate --project="$GCP_PROJECT_ID" \
    --permissions="$permissions" --stage=GA >/dev/null
else
  gcloud iam roles create pharmaGuardVmUpdate --project="$GCP_PROJECT_ID" \
    --title="PharmaGuard existing VM metadata updates" --permissions="$permissions" --stage=GA >/dev/null
fi
gcloud compute instances add-iam-policy-binding pharmaguard-hackathon \
  --project="$GCP_PROJECT_ID" --zone="$GCP_ZONE" --member="$member" \
  --role="projects/$GCP_PROJECT_ID/roles/pharmaGuardVmUpdate" >/dev/null
printf 'GCP_WIF_PROVIDER=projects/%s/locations/global/workloadIdentityPools/%s/providers/%s\n' "$PROJECT_NUMBER" "$POOL" "$PROVIDER"
