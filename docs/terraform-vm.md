# Persistent application VM deployment

Terraform lives under `infra/terraform/environments/production` and the reusable
`modules/application_vm` module. It owns only new application VM/network/IAM resources.
Existing Cloud SQL, raw GCS data, Qdrant and registry are reused; they are not recreated or
imported into this state. No secret versions/payloads are Terraform resources or data sources.
Secret **references** and resource identifiers are non-secret configuration.

The environment directory name does not determine Terraform resource addresses. The
existing backend prefix, cloud resource IDs and CI resource-group keys remain stable
to preserve state ownership and serialize older and newer release pipelines. Changing
those identifiers requires a separate migration; this directory rename creates no resources.

The default VM is `e2-standard-2` (2 vCPU, 8 GiB) with a 30 GiB balanced boot disk. This allows
bounded candidate/previous-container overlap during deployment. The deployment uses a
single machine; high availability is not provided. Application containers run
as non-root with read-only root filesystems, dropped capabilities, memory/CPU bounds and
temporary writable scratch space. Database and Qdrant remain external and persistent.

Reuse avoids rebuild/setup time, but does not inherently reduce cloud billing: a running idle
VM is billed continuously. Cloud Run with zero minimum instances can be cheaper for sparse
traffic. Disk, existing SQL, storage, Qdrant, network/IPv4 and logging can incur separate
charges. Stopping compute preserves data and still incurs disk charges. See Google's
[VM pricing](https://cloud.google.com/products/compute/pricing) and
[disk pricing](https://cloud.google.com/compute/disks-image-pricing).

The stop timer preserves service through **19 November 2026 IST** and uses
**2026-11-20 00:00 IST** (`2026-11-19T18:30:00Z`). It powers off,
never deletes the VM or disk. A persistent systemd timer also prevents a later reboot from
quietly extending the expired deployment. Extending requires an explicit configuration change.
Expiry does not stop the existing Cloud SQL database or delete storage.

## Topology and identity

The public Cloud Run HTTPS entry point reaches the VM's private address `10.73.0.2:8080`.
The separate staging preview reaches `10.73.0.2:8081`. Each listener has its own release pin:

| Channel | Cloud Run service | Source subnet | VM listener | Release state |
| --- | --- | --- | --- | --- |
| Production | `pharmaguard-web` | `pg-edge`, `10.73.1.0/26` | `8080` | `production.json` |
| Staging | `pharmaguard-vm-preview` | `pg-preview`, `10.73.2.0/26` | `8081` | `active.json` |

A staging update uses the slot opposite production. Repeated unpromoted updates reuse that
staging slot; they cannot stop the production containers or change its listener. The existing
legacy backend is adopted only after its served SHA matches its recorded manifest. A fresh
installation serves 503 on production until a human approves its first promotion.

The VM hosts Next.js and the backend. Backend/SQL proxy have no host-public ports; Nginx
routes to loopback-published web containers. Ingress firewall rules allow each subnet only
its corresponding listener and SSH only from IAP. Cloud Run Direct VPC network tags cannot
be used as ingress firewall sources, so distinct subnet CIDRs enforce this boundary; see
[Google's Direct VPC limitations and firewall guidance](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc).
No Internet SSH/application ingress is opened. OS Login and Shielded VM are enabled.
The external ephemeral IP is for outbound Qdrant/registry access, avoiding a separate NAT
gateway; it is not a public app URL.

This isolates release routing and container lifecycle, not CPU, RAM, the host, or canonical
storage. Both slots use the existing SQL/Qdrant dataset and shared usage budget. Additive
migrations must remain compatible with production. Replacing an unpromoted staging candidate
can briefly interrupt staging. Failure leaves production pinned, but staging may require a
retry. A host failure still affects both channels. Shared SQL proxy changes are rejected by
staging and require a separate maintenance operation.

The dedicated VM service account can read the runtime configuration and its required secrets,
invoke Vertex, connect to SQL, pull images and write telemetry. It cannot read the ingestion
configuration, create secrets, deploy services or modify canonical data. Docker web-container
addresses are blocked from the metadata identity endpoint; the API/SQL proxy use ADC metadata.
Host root is still trusted. This is defense in depth, not complete isolation of a compromised VM.

State uses a separate private, uniform-access, versioned GCS bucket with native locking.
`infra.prepare_terraform` bootstraps it with owner ADC; GitLab later uses restricted WIF.
Never commit state, saved plans, `.terraform`, credentials or raw corpora. Plans/artifacts
are restricted to maintainers; Duo receives the sanitized plan summary, not state/credentials.
The separate `terraform:evidence` job publishes only policy-checked resource addresses and
actions. It does not publish the full plan or startup metadata.
HashiCorp documents [GCS locking and versioning](https://developer.hashicorp.com/terraform/language/backend/gcs).

## Owner workflow before GitLab access

```powershell
uv run python -m infra.prepare_terraform --project YOUR_PROJECT
terraform -chdir=infra/terraform/environments/production init -backend-config="bucket=YOUR_STATE_BUCKET" -backend-config="prefix=hackathon/application-vm"
terraform -chdir=infra/terraform/environments/production plan -var="project_id=YOUR_PROJECT" -out=../../../../.data/vm.tfplan
terraform -chdir=infra/terraform/environments/production show -json ../../../../.data/vm.tfplan > .data/terraform-plan.json
uv run python ci/terraform_policy.py .data/terraform-plan.json .data/terraform-summary.json
terraform -chdir=infra/terraform/environments/production apply ../../../../.data/vm.tfplan
```

Terraform is pinned through its provider lockfile. `prevent_destroy`, Compute Engine deletion
protection and the plan-policy checker reject replacement/deletion. Application releases do
not edit VM identity/disk. A machine-type change may stop/update the existing VM with downtime;
immutable hardware changes fail instead of silently replacing it. Plan every change.

Build the API/web/edge images using `cloudbuild.yaml` or the GitLab packaging job and resolve
digests. Use a pinned Cloud SQL Auth Proxy image digest too. `infra.deploy_vm` runs additive
migrations as the separate ingestion identity in Cloud Run, then transfers only a non-secret
release manifest through IAP. The VM pulls images with a short-lived metadata token, removes
its temporary `/run` Docker login file, and fetches runtime credentials from Secret Manager.

```powershell
uv run python -m infra.deploy_vm --project YOUR_PROJECT --api-image API_DIGEST --web-image WEB_DIGEST --sql-proxy-image SQL_PROXY_DIGEST --sha SOURCE_SHA --runtime-version CONFIG_VERSION
```

`infra/vm/release.py` stages alternate API/web containers, verifies readiness and the actual
source SHA, tests Nginx configuration, and changes **only listener 8081**. It verifies that
listener 8080 still serves the production manifest. CI additionally records the public source
before deployment, after deployment, and after the preview smoke. Any source change fails
release evidence. The real Docker/Nginx routing gate exercises ten staging route changes;
controller tests separately exercise ten staging releases, failures, stale approvals and boot.

A separate human-approved production job supplies the exact packaged manifest. The controller
rejects a stale approval if staging has changed, verifies both running image digests, then
switches listener 8080 and atomically records `production.json`. A failed health check restores
the previous route. Only after successful promotion does it stop the old production slot.
On reboot, `--restore` starts and verifies the approved production slot independently of the
last staging manifest. First staging on a fresh installation does not approve production.

Owner recovery uses the same digest/configuration arguments as deployment. `--rollback`
accepts only the recorded previous **production** manifest and stages it without rerunning old
migrations. Verify staging, then use `--promote` only after human approval. Neither flag changes
the controller from an older checkout. There is no schema downgrade or data deletion.
A Cloud Run edge rollback alone does not restore a previous VM application: use the recorded
application manifest for that recovery. The retained standalone Cloud Run application revision
is an independent emergency option requiring explicit approval.

Image packaging runs on CI workers, not on this VM. A resource group serializes packaging;
retries of the same commit reuse an already-published image. A shared deployment/promotion
resource group plus a host file lock serializes VM changes. At most two API/web slots run.
Cleanup retains current production, previous production and current staging images, protects
every container's image, and removes only unreferenced images from the application's API/web
repositories. There is no global prune or volume deletion. New releases require 5 GiB disk
reserve and 4 GiB available memory after stopping only a replaceable staging candidate.
A healthy identical release needs no new slot. Unsafe capacity blocks deployment instead of
resizing the VM. Retention tests preserve unrelated workloads and the production slot.

## GitLab layout and activation

`.gitlab/ci/` contains base templates, validation, security, evaluation, packaging, Terraform,
Cloud Run, VM and governance jobs. Set `DEPLOY_TARGET=vm` to select the new path; the existing
Cloud Run path remains the default. Protected variables contain non-secret IDs/references:
`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ZONE`, `GCP_WIF_PROVIDER`, deployment service account,
`TF_STATE_BUCKET`, `RUNTIME_CONFIG_REFERENCE`, `INGEST_CONFIG_VERSION`,
`CLOUD_SQL_CONNECTION_NAME`, `SQL_PROXY_IMAGE`, `VM_EXPIRES_AT`, `WEB_URL`, and reviewed smoke
expectations. Packaging exports immutable API/web/edge digests, never API keys.

All existing tests, audits and the frozen RAG gate block packaging. VM infrastructure apply
is manual, with state locking and a resource group. VM deployment runs readiness and emits
release evidence. Public entry-point promotion is a separate human action, followed by the
full reviewed public investigation smoke. No automatic production approval or merge is added.
The promotion script selects the newly created revision, verifies its immutable edge-image
digest and its own `Ready=True` condition, then explicitly assigns it 100% traffic. The service's
`latestReadyRevisionName` can still identify an older revision when the new revision has zero
traffic, so it is not used to select the promotion target. This is required after a rollback because Cloud Run preserves the
previous revision's traffic assignment on subsequent deployments; see
[Cloud Run traffic lifecycle](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration#lifecycle_of_traffic_splits).
The deploy identity needs permissions for state objects, Compute Engine, IAP, OS Login and actAs
for this VM and existing Cloud Run migration rights. Do not grant owner/editor or trust an
unofficial GitLab project. Exact WIF project/group/branch claims remain mandatory.

The checked-in Duo flow can inspect `evaluation/report.json`,
`deployment/terraform-summary.json`, `deployment/release-evidence.json`, sanitized JSONL events
and actual job links. The current successful-release flow is read-only with respect to product
code, gates, labels, Terraform policy, approval jobs and secrets. Future repair requires a
separately requested task. The official project, hosted runners and enabled flow are verified;
protected-main WIF exchange and GitLab-operated staging remain separate acceptance checks.
