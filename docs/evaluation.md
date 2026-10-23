# RAG evaluation and supervised release

## Review labels before running the gate

Select 10–20 cases from a published real corpus. Inspect the exact canonical text, source
version, and cutoff dates. Label required chunk IDs and critical evidence independently of
the current retrieval ranking. Include multi-source/multi-chunk questions so losing evidence
is meaningful. A generated candidate is not a reviewed case.

Each case JSON contains `case_id`, `question`, optional `drug`/`event`, `cutoff_date`,
`required_evidence_ids`, `critical_evidence_ids`, `expected_facts`, `reviewed_by`, and
`review_note`, and reviewed `expected_answer_points`. Expected facts use the API's complete `SignalFacts` contract, including dataset
lineage. Case IDs are immutable; corrected labels require an explicit new dataset version.

```powershell
uv run pharmaguard-eval import-cases DATASET_ID .data/reviewed-cases.json
uv run pharmaguard-eval export DATASET_ID v1 .data/evaluation/snapshot.zip
uv run pharmaguard-eval run .data/evaluation/snapshot.zip
```

The ZIP contains a canonical manifest and streaming JSONL report/drug/reaction tables, with
fixed member timestamps and a SHA256 sidecar. It does not require loading the full FAERS
comparison population into RAM. Keep large snapshots outside Git, in GCS and/or the GitLab
Generic Package Registry. To evaluate in CI, restore into an **empty, disposable database**
with `--restore-data`. Existing databases are rejected.

Publish the approved snapshot as the GitLab Generic Package
`pharmaguard-eval/VERSION/snapshot.zip`, then set non-secret `EVAL_DATASET_VERSION` and
`EVAL_SNAPSHOT_SHA256` CI variables. Freeze these independently from the product MR.
CI fetches it with `CI_JOB_TOKEN` and verifies the approved checksum. Model revisions must match.

## Blocking policy

- Recall@5 at least 0.80 for every case.
- All critical evidence retrieved.
- No source/publication availability after the cutoff, or before the configured window.
- Canonical citation eligibility and exact deterministic fact agreement.

These checks measure retrieval, facts, and citation integrity. They do not independently
establish semantic entailment or clinical truth. Live Gemini synthesis is tested separately,
and the deployed investigation path always validates generated citations against retrieved IDs.

## Prepared inputs for repeated deployment testing

The fast CI path uses two immutable, project-owned container images. They cache **inputs**,
never reports, rankings or calculated fact results:

- `ci/evaluation/Dockerfile.database` verifies the approved ZIP checksum, restores the complete
  report population into a clean PostgreSQL 15 cluster, vacuums/analyzes it and shuts it down
  cleanly. Its final image contains only that isolated public benchmark database, with no
  production roles, credentials, session data or local database copied into it.
- `ci/evaluation/Dockerfile.runtime` contains locked Python dependencies and the pinned MedCPT
  model files. CI installs the current checkout into its environment, so product changes are
  always evaluated rather than executing an old application's code.

The optional checksum-pinned `articles-SHA256.json.gz` input contains only article vectors
computed from the approved title/body pairs. It is tied to the corpus checksum, model revision,
encoder implementation, dependency lock and input format. Changed encoder code/dependencies
or changed text execute the current encoder instead. Query embeddings, candidate selection,
reranking, facts and case comparisons always execute afresh. Current indexing code still
rebuilds a fresh Qdrant collection from canonical rows on every run.

An authorized operator prepares/publishes these once per snapshot, migration schema, dependency
lock or model revision change. From a clean checkout, with registry authentication already set:

```bash
docker buildx build --shm-size=1g -f ci/evaluation/Dockerfile.database \
  --build-arg SNAPSHOT_URL=APPROVED_PACKAGE_URL \
  --build-arg SNAPSHOT_SHA256=APPROVED_SHA256 \
  --output "type=image,name=$CI_REGISTRY_IMAGE/evaluation-database:INPUT_VERSION,push=true,compression=zstd,compression-level=3,force-compression=true,oci-mediatypes=true" .
docker build -f ci/evaluation/Dockerfile.runtime \
  -t "$CI_REGISTRY_IMAGE/evaluation-runtime:INPUT_VERSION" .
docker push "$CI_REGISTRY_IMAGE/evaluation-runtime:INPUT_VERSION"
uv run python -m evaluation.embedding_inputs --snapshot PATH_TO_APPROVED_ZIP \
  --sha256 APPROVED_SHA256 --output .data/evaluation/articles.json.gz
```

Resolve and configure `EVAL_DATABASE_IMAGE` and `EVAL_RUNTIME_IMAGE` as `repository@sha256:...`
CI variables, independently of product changes. Mutable tag references are rejected. The
database image uses passwordless trust only inside its disposable CI service network; never
deploy it as an application database or publish its PostgreSQL port to the Internet.

Publish the generated article input as the same Generic Package version's
`articles-SHA256.json.gz` and set `EVAL_EMBEDDING_SHA256` to that exact digest. No raw data or
vectors are committed to Git. The RAG job requests the isolated
[`saas-linux-large-amd64` runner](https://docs.gitlab.com/ci/runners/hosted_runners/linux/)
(8 vCPUs, Premium/Ultimate) with four bounded case workers and two model threads each. It never
runs on the application VM. Each worker owns its database session and tokenizer state;
read-only model weights are shared in evaluation/inference mode. All ten cases still produce
individual comparison results. The seed uses file-backed dynamic shared memory so Docker's
small default `/dev/shm` cannot break PostgreSQL maintenance or parallel queries.
OCI [Zstandard compression](https://docs.docker.com/build/exporters/image-registry/) reduces
repeated input-image startup overhead without changing database files.
GitLab's [compute multiplier](https://docs.gitlab.com/ci/pipelines/compute_minutes/) for this
runner is three; compare actual duration multiplied by three with the 22.5-minute small-runner
baseline. Do not purchase capacity or upgrade the subscription automatically.

Every job validates the approved snapshot checksum, prepared database marker, exact canonical
document/chunk/entity contents, memberships and all background-table counts. It rebuilds the
Qdrant index with current indexing code and executes every reviewed retrieval case. Identical
fact inputs within one run share one production SQL calculation; distinct pair/cutoff inputs
are all recomputed. No result is shared between runs. Thresholds and labels remain unchanged.
`evaluation/report.json` records `input_mode` and `timing_seconds` for measured performance.

The one-time seed build is intentionally outside the two-minute repeat-run target. Cold image
pulls and runner queues can exceed the target even when evaluation itself is fast; report actual
job duration separately. Full fresh restoration remains available with `--restore-data` for
dataset/schema changes and reproduction. It is never substituted with a smaller population.

## Deliberate regression

Start with an independently labeled, passing benchmark. Create a separate Git branch and
change only `config/retrieval.json` from `top_k=5` to `top_k=1`. Ordinary lint, unit, API,
browser, and security checks should still pass. Multi-evidence/critical cases must fail the
RAG gate, preventing packaging/deployment. Repeat the baseline/regression comparison twice.
Restore the product configuration; never change required labels or thresholds to obtain green.

## Register GitLab Duo

The repository contains `AGENTS.md`, the `rag-release-safety` skill, and the supervised flow
YAML. Repository files alone do not register a running GitLab flow. Once official access arrives:

1. Confirm hosted runners, AI credits, and the required project/group permissions.
2. Create the custom flow in GitLab AI Flows/Catalog using the checked-in YAML; validate it
   against the schema supported by that GitLab instance.
3. Configure its execution environment with Python/uv, Node/pnpm, and the available GitLab CLI.
4. Enable the flow in the application project and configure an MR mention/reviewer trigger.
5. Invoke it on the regression MR and verify the real session reads evaluation artifacts.
6. Permit one bounded product repair. CI remains authoritative; the agent may not alter
   labels, checksums, thresholds, tests, pipeline dependencies, or security gates.
7. Inspect successful staging smoke evidence and record a separate human governance approval.

Current setup follows GitLab's [custom-flow schema](https://docs.gitlab.com/user/duo_agent_platform/flows/custom_flows_schema/)
and [flow registration requirements](https://docs.gitlab.com/user/duo_agent_platform/flows/custom/).
Tool availability and instance-side validation remain remote acceptance checks.

## Separate live LLM judge

Run `pharmaguard-eval judge .data/evaluation/snapshot.zip` after the deterministic baseline.
It generates real answers with the configured provider chain and uses a separately configured
model to assess groundedness, correctness, reference-point coverage, and safety. It rejects
using the identical answer model as its own judge. Reference points must be reviewed before
this command; an empty reference fails closed. The report records both model identities,
actual answers, citation IDs, scores, and unsupported claims. A judge can be wrong; deterministic
checks and reviewed ground truth remain mandatory. Judge output never rewrites labels.


## Source version review and current local evidence

A first candidate review incorrectly used three historical PubMed cutoffs before the current
XML record's revision date. That candidate file is retained as rejected evidence, not an
approved benchmark. The new review retains the questions, required passages, critical markers,
and reference points, and corrects only those three cutoffs. Archived DailyMed and the eligible
PubMed historical case still exercise historical retrieval. Labels are never taken from ranks.

The first dense-only baseline failed four cases. Title/body inputs alone remained insufficient.
The current pipeline recovered all required evidence in all ten source-reviewed local retrieval
cases: bounded exact-term and dense candidates, a MedCPT reranker, short-abstract context,
and an eligible regulatory warning anchor. The full frozen-background gates subsequently passed locally and in Cloud Run.
The final separate live judge passed all ten cases and rejected its false-causality
control; source review and human domain sign-off remain distinct requirements.

`evaluation.reference` derives expected contingency cells through an independent PostgreSQL
DISTINCT ON / set-join query. It does not call the product's window-based metric calculation.
Snapshots preserve completed ingestion manifests, model revisions, and the reranker format.
Restoration uses COPY and an evaluation-specific Qdrant namespace.

When a local SQL proxy is unavailable, `evaluation.cloud_runner` runs beside Cloud SQL using
`pg-eval-sa`. This identity can read only the required secrets and can read/create artifacts only
under the bucket's `evaluation/` prefix. It cannot publish services. `infra/run_evaluation.py`
deploys the job by immutable digest. The deterministic gate and live judge remain separate jobs.

The first full cloud gate retained exact facts and temporal safety but failed one critical
retrieval case. That failure is preserved under `evaluation/runs/baseline-f7fbf2e/` in GCS.
The dynamic-int8 ranking path was replaced with float32; repeated full cloud gates
then passed without changing labels or thresholds. Labels, thresholds, and the frozen snapshot stay fixed.


Final execution evidence and immutable image digests are in
[the verification guide](verification.md). The live synthesis contract uses
cited paragraphs with allowed-ID enums. The server validates every paragraph before
rendering source markers; citation failures do not trigger a provider retry.
