# Structured operational logs and release evidence

Application events are JSON with UTC timestamps, severity and correlation identifiers.
`pharmaguard.observability.event` accepts only an explicit field allowlist; passing a prompt,
answer, token, authorization header or arbitrary provider response field fails closed.
Request context propagates request ID and Git SHA into synchronous retrieval events.
No full user question, session JWT, environment dump, database password or provider key is
logged. Session UUIDs are pseudonymous correlation identifiers, not access credentials.

| Area | Events and useful fields |
| --- | --- |
| HTTP | route, method, status, duration_ms, request_id, app_version, git_sha |
| Investigation | dataset_id, facts_ms, retrieval_ms, synthesis_ms, request_id |
| Retrieval | retrieval_started/completed, candidate_count, returned, top_k, config_version, duration_ms |
| Cache | answer_cache, session_id, dataset_id, cache_status=hit/miss, retained history count |
| Ingestion | ingestion_stage_started/completed/failed, run_id, dataset_id, stage, duration_ms, immutable manifest URI, error_type |
| Deployment | started, operation_failed, candidate_ready, rollback, completed/failed; git_sha, image_digest, slot, status, error_type |
| Terraform | saved plan plus sanitized address/actions summary; delete/replacement is rejected before apply |

Ingestion retains detailed counts, checksums, source/version/window lineage and failure status
in PostgreSQL `ingestion_run` and immutable GCS stage manifests. Log entries link to that
manifest rather than repeating corpus text. Never log source HTTP exception bodies or signed
URLs that might contain credentials. Failed operations propagate; logs do not convert them to
success. API dependency errors have typed codes and request IDs. Unhandled exception logging
records only the exception class to prevent SQL parameter/provider-header disclosure.

Cloud Run captures JSON stdout/stderr automatically. The VM uses journald for container logs,
and the Google Ops Agent forwards the journal and parses the deployment JSONL stream into
Cloud Logging. Root-only `/opt/pharmaguard/deployment.jsonl` preserves the release audit trail.
Limit retention/access in Cloud Logging to operational requirements; never make logs public.

Typical Logs Explorer filters (replace identifiers):

```text
resource.type="cloud_run_revision" jsonPayload.request_id="REQUEST_UUID"
resource.type="cloud_run_job" jsonPayload.run_id="INGESTION_RUN_UUID"
resource.type="gce_instance" jsonPayload.event="deployment_completed"
```

Container JSON inside journal entries can appear nested as a journal message; inspect the
journal payload/message when searching API events on the VM. Filter by instance ID and
request UUID rather than exporting the whole journal. Routine health polling can be excluded
from long-term sinks if needed without suppressing investigation/error/release evidence.

GitLab keeps failed and successful job artifacts. `ci/release_evidence.py` accepts actual
deployment-completed events and readiness, exports only approved fields, includes the real
pipeline URL, and explicitly marks public smoke/production approval/Duo activation pending
when they have not happened. Readiness is not an answer-quality pass. Deterministic benchmark,
separate live judge and reviewed public smoke remain distinct artifacts and blocking checks.

Duo's future review bundle consists of the MR diff, job URLs, evaluation report, sanitized
Terraform summary, release manifest containing digests/references, release-evidence JSON and
deployment events. It excludes state, JWTs, secret payloads, complete environment dumps and
unrestricted host logs. Keep artifact access limited to maintainers. Repository YAML alone
does not register or grant permissions to a GitLab Duo flow.
