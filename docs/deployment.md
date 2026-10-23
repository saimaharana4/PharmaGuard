# GCP deployment

## Existing resource inventory

| Resource | Identifier |
| --- | --- |
| Project | `project-bb13ecd8-9d67-408d-9a7` |
| Project number | `902056825143` |
| Region | `asia-south1` |
| Cloud SQL | `pg-pharmaguard-hackathon` / PostgreSQL 15 |
| Database / ingestion user | `pharmaguard` / `pharmaguard_app` |
| API database user | `pharmaguard_runtime` (canonical SELECT and budget writes only) |
| Raw bucket | `pharmaguard-hackathon-project-bb13ecd8-9d67-408d-9a7` |
| Artifact Registry | `asia-south1-docker.pkg.dev/project-bb13ecd8-9d67-408d-9a7/pharmaguard-hackathon` |
| Runtime identity | `pg-runtime-sa` |
| Ingestion identity | `pg-ingest-sa` |
| GitLab deployment identity | `pg-gitlab-deploy-sa` |
| Database password secret | `pg-db-password` |
| Qdrant secret | `pg-qdrant-api-key` |

Non-secret identifiers above are configuration defaults, not values embedded in business logic.
`infra/verify_gcp.ps1` records live metadata under ignored `.data/gcp-inventory`.

## Bootstrap deployment

Use Google Cloud SDK with the account authorized for this project. Run
`infra/configure_runtime.sh` from Bash/Cloud Shell after exporting `GCP_PROJECT_ID`. It enables
Vertex AI and grants the dedicated runtime identity model access. It preserves existing SQL
data and does not create service-account keys.

Build images locally with the two Dockerfiles, or use the supplied Cloud Build configuration:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions="_REGISTRY=$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/pharmaguard-hackathon,_SOURCE_SHA=$(git rev-parse HEAD)"
```

The Cloud Build identity needs write access to the existing artifact repository, permission
to write build logs, and access to the source staging bucket. The source upload excludes `.env`,
datasets, model caches, local tools, and the original credential-bearing transcript.

Resolve the resulting images to `@sha256:...` digests. Owner bootstrap uses:

```powershell
uv run python -m infra.provision_runtime --project YOUR_PROJECT
uv run python -m infra.deploy_cloud --project YOUR_PROJECT --api-image API_DIGEST --web-image WEB_DIGEST --sha SOURCE_SHA --release-manifest gs://BUCKET/manifests/releases.json --runtime-config-version CONFIG_VERSION --ingest-config-version CONFIG_VERSION --ingest
```

The migration and ingestion identities read `pg-config-ingest`; the API reads
`pg-config-runtime`. All configuration and credentials use pinned Secret Manager versions.
Only a resource reference is supplied as `APP_CONFIG_SECRET`. No `.env` file or API key is baked
into an image. Model names, including the answer, judge, fallback, and MedCPT model settings,
are held in the configuration secret.

Only the web UI is publicly accessible. Its dedicated `pg-web-sa` identity can invoke the
private API, but cannot read database/model secrets. The web proxy obtains a short-lived
Google identity token from the metadata server. It does not forward caller credentials.
PostgreSQL enforces a shared daily investigation budget across API instances. The browser
receives a nonce-based Content Security Policy and model output is rendered as text.
Anonymous access can still be abused; these controls do not promise complete security or availability.

For GitLab deployments, `ci/deploy_cloudrun.sh` preserves those established IAM boundaries.
Final production promotion remains a human action.

## Ingest in GCP

Upload the reviewed release manifest to GCS, export `FAERS_RELEASE_MANIFEST=gs://...`, and run
`bash infra/deploy_ingestion.sh`. Execute `gcloud run jobs execute pharmaguard-ingest --wait`.
The job loads the full background population from selected releases and publishes only after
all stages pass. It has one task, two CPUs, 8 GiB RAM, bounded execution, and no automatic retries.

Raw objects and manifests stay in GCS. The online API never parses raw source objects.
The API uses two CPUs and one concurrent investigation per instance. Online models are
preloaded before startup completes when `preload_models` is enabled in the runtime secret.
API/web default to zero minimum instances and three maximum instances. Model weights are
cached in the API image at pinned revisions to avoid runtime model downloads.

## GitLab WIF

After the official project is provisioned, export the numeric GitLab group/project IDs and
default branch, then run `infra/configure_wif.sh` as project owner. Trust is restricted to
the exact group, project, protected default branch, and protected-ref claim. Set protected
CI variables for the provider resource and deployment identity. No JSON service-account key
is needed. Read-only merge-request gates use GitLab job tokens, not deployment credentials.

## Verification and rollback

Postdeploy smoke checks health, readiness, and a reviewed real investigation with required
citation IDs. Configure `SMOKE_QUESTION`, `SMOKE_REQUIRED_EVIDENCE_IDS`, and, for a
historical case, `SMOKE_CUTOFF_DATE` from a reviewed benchmark case. Missing expectations
fail the smoke test. Record the image digest, source SHA,
active dataset, and Cloud Run revision in release evidence.

Keep the previous ready revisions. To roll back an application service:

```bash
gcloud run services update-traffic pharmaguard-api --region="$GCP_REGION" --to-revisions=PREVIOUS_REVISION=100
gcloud run services update-traffic pharmaguard-web --region="$GCP_REGION" --to-revisions=PREVIOUS_REVISION=100
```

Schema changes must remain compatible with retained revisions. Data rollback is a separate,
explicit active-dataset change; retain the old canonical rows and collection. Never delete
the existing SQL instance, bucket, or database to recover an application revision.


Credential rotation creates a new password version and new pinned configuration versions.
Use those explicit versions in bootstrap arguments and GitLab's `RUNTIME_CONFIG_VERSION` /
`INGEST_CONFIG_VERSION`; version 1 is not implicitly the current configuration. The scoped
`infra.rotate_database_password` utility updates only the application database user and
keeps secret values out of files, command arguments, and logs.

The persistent VM path uses separate private listeners and source subnets for production and
staging. Staging updates preserve the production pin; human approval switches it only after
readiness, source/digest checks and the reviewed investigation pass. See
[Terraform/VM operations](terraform-vm.md) for routing, boot recovery, rollback and shared-host
limits. Cloud Run remains the public HTTPS entry point.
