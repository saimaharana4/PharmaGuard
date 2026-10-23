# GitLab operations

The [Wiki](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/wikis/Home)
connects planning, environment links, immutable release evidence and private monitoring.
Features are used where they support real work; unavailable integrations are not represented
as enabled. No additional account, paid telemetry backend or long-lived credential is required.

## Planning and traceability

Three group epics, three milestones and a workflow board organize real work. Seven native
Requirements describe tested contracts. Ten native Test Cases are copied from the immutable,
reviewed v2 benchmark. The bootstrap verifies the snapshot checksum first. Marker-based
upserts preserve human edits and avoid duplicate issues, Tasks, requirements and cases.
Retrospective issues retain their actual creation dates and link original release evidence.

```powershell
uv run python -m operations.workspace --snapshot .data/evaluation/snapshot.zip
uv run python -m operations.workspace --snapshot .data/evaluation/snapshot.zip --apply
uv run python -m operations.wiki --apply
```

GitLab CLI authentication stays in the OS keyring. These owner-operated utilities use the
current account's existing permissions. They do not run automatically in application containers.
Wiki sources are in `docs/gitlab/wiki/`; the publisher refuses to replace unmanaged pages.
Do not backfill fabricated dates, mark generated labels reviewed, or close unverified work.

## Test reporting

Backend unit tests publish JUnit and Cobertura coverage. Real PostgreSQL/Qdrant integration,
Docker routing, Vitest and desktop/mobile Playwright suites publish their own JUnit output.
The frozen RAG converter emits five measured checks per reviewed case, preserving recall,
critical evidence, citation eligibility, temporal safety and exact facts. It rejects malformed
or contradictory reports and makes no model calls. Failed evaluation remains a failed gate.

Coverage is reported for inspection; this change introduces no arbitrary percentage gate.
The deterministic benchmark thresholds and frozen snapshot remain unchanged. Live semantic
judging remains separate from deterministic evaluation.

## Native security

The Next 16.4.2 ESLint plugin's sole `fast-glob` call is `globSync` with
`onlyDirectories: true`. A version-scoped pnpm override substitutes pinned
`tinyglobby@0.2.17` for that dependency, removing the `micromatch` / `braces` chain
(GHSA-vfj7-8cjw-p6xm). All Next, React and TypeScript lint rules remain enabled.
Regression checks verify the plugin's actual dependency resolution, equivalent filesystem
roots for default/wildcard/multiple/brace/Windows patterns, and detection of invalid internal
links and image usage through the complete ESLint configuration. Directory strings can be
relative with trailing separators; the tests compare their resolved filesystem targets.
This override is scoped to the pinned plugin version and must be reviewed when upgrading Next.

Official GitLab templates produce SAST, IaC, secret-detection, dependency-scanning and CycloneDX
reports. Existing pip-audit, explicit upstream Torch audit, pnpm audit and Gitleaks gates remain.
Analyzer failures block release. A separate policy job checks successfully produced native reports:
high, critical and unknown-severity findings block; every secret finding blocks. Other findings
remain visible. The pipeline never creates an empty report to stand in for an unexecuted scan.

Protected-main packaging builds each image once. A matrix scans API/web/edge **by immutable
digest** using GitLab's container analyzer. Its Ruby wrapper exchanges the existing protected
OIDC identity through Google STS and service-account impersonation, retaining registry access
tokens only in process memory. No new key, registry copy, gcloud installation or image build is
needed by that job. All three reports must exist and pass policy before Terraform apply or
Cloud Run deployment. Feature branches do not receive deployment credentials.

Native report configuration is not execution evidence. Inspect the exact pipeline's Security,
Tests and dependency views. Protected-main container authentication/scanning is verified only
when those jobs actually run after a human merge. Newly reported vulnerabilities must be
reviewed and fixed; do not hide them, relax gates or skip scans for a green demonstration.

## Release evidence and environments

Production release `v0.1.0` identifies commit `3a724e29`. Its evidence package records
32 successful release jobs, the frozen RAG report, cited staging/public smoke tests,
immutable image digests, security summaries and retained-resource verification. The
staging investigation completed in 31.93 seconds; production completed in 30.09 seconds.
Release notes describe product changes, compatibility, verification and known limitations.
Publishing release metadata does not promote another application revision.

`python -m operations.evidence INPUT_DIRECTORY OUTPUT.zip` validates the original baseline and
packages only allowlisted JSON. Files have deterministic ZIP timestamps and SHA256 checksums.
It rejects credential-like fields/values, symlinks, unexpected sizes and mismatched source/results.
Raw traces, Terraform state/plans, corpora and weights must not be uploaded as release evidence.

Staging and production have different URLs and explicit GitLab deployment tiers. Human merge,
manual Terraform apply and human production promotion remain in force. Environment settings
do not alter Cloud Run traffic or the VM production pin.

## Monitoring and analysis

`uv run python -m operations.monitoring --apply` maintains one private GCP dashboard by name
using ADC and existing telemetry. VM CPU/memory and Cloud Run request/error/latency charts
were queried against actual samples. It creates no telemetry backend, agent, alert channel or VM.
No prompts, answers, tokens or secret payloads are added. The Wiki links existing Cloud Logging,
pipeline analytics, environments and release evidence. Smoke timing is a point-in-time result,
not a continuous uptime claim. Hosted Observability and integrations requiring extra setup are
intentionally omitted.
