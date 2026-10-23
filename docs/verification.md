# Verification evidence

Results below distinguish a deployed baseline from later reporting work. A configuration file,
green unit suite or owner-operated cloud check does not establish deployment success.

## Current production release

[PharmaGuard AI v0.1.0](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/releases/v0.1.0)
records source `3a724e294892dce03ff89a1a0edcbe5fb2b973ff` and
[pipeline 2964871282](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines/2964871282).
All 32 latest jobs passed, including immutable-image security checks, Terraform,
staging deployment, production promotion, public smoke and final governance.

| Check | Observed result |
| --- | --- |
| Frozen RAG | 10/10 reviewed cases passed; exact facts, critical evidence, citation eligibility and zero temporal leakage |
| Staging investigation | Required citations present; 31.93 seconds |
| Public investigation | Required citations present; 30.09 seconds |
| Production revision | `pharmaguard-web-00013-pwh` |
| Terraform | 0 created, 4 updated in place, 0 destroyed; original VM retained |
| Routing | Production stayed pinned during staging; both HTTPS sources match the released commit after approval |
| Security | Source and all three image policies passed; lower-severity findings remain in native reports |

The release links downloadable sanitized evidence with SHA256 checksums. The following
baseline and feature checks are historical records and retain their original source context.

## Earlier deployment baseline

Source `a3eeebea0931d1c422132612cf0ceba74601b6a2` completed
[pipeline 2964230916](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines/2964230916)
with **20 successful latest jobs**, including packaging, keyless WIF, Terraform, staging, human
production promotion, public smoke and final human governance. Failed attempts remain in history.

| Task | Observed result |
| --- | --- |
| Frozen v2 RAG | All ten cases passed with Recall@5 1.00; exact facts, critical evidence, eligible citations and zero temporal leakage |
| Staging investigation | Real cited investigation passed in 33.03 seconds |
| Public investigation | Real cited investigation passed in 30.26 seconds |
| Production revision | `pharmaguard-web-00012-jxt`; exact packaged edge digest verified |
| Independent routing | Staging served the candidate while production retained its approved source; human approval switched the production pin afterward |
| VM/data preservation | Same VM identity and disk retained; no instance replacement; canonical data preserved |
| Terraform recovery | Partial apply followed by stale-plan failure preserved; fresh reviewed apply added only preview subnet/firewall, no destruction; temporary narrow IAM binding revoked |
| Anonymous browser | Desktop/mobile ready states, keyboard interaction, disclaimer and no overflow verified |
| Human governance | Production job 17292303412 and final governance job 17292303414 completed successfully |

[Earlier verification bundle](https://gitlab.com/api/v4/projects/87777712/packages/generic/release-evidence/a3eeebea/release-evidence.zip)
provides sanitized JSON evidence and checksums. Raw traces, credentials and Terraform state are
excluded. The [Wiki](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/wikis/Release-evidence)
records exact image digests and the frozen snapshot checksum.

## Reporting and operations changes

Local verification on the operations feature branch:

- Ruff lint/format and frontend lint/typecheck/production build passed.
- 141 backend unit/API checks passed; the Docker-only routing check was run separately and passed.
- Two real PostgreSQL/Qdrant integration tests passed against the existing Compose dependencies.
- Ten frontend unit tests and ten desktop/mobile Playwright scenarios passed, including archived
  DailyMed new-tab navigation, retry, abstention and request validation.
- Native Wiki, three epics, three milestones, seven Requirements, ten reviewed Test Cases and board
  workflow were created. Rerunning the bootstrap preserved the same records.
- Release package download matched its SHA256. Environment links and deployment tiers were verified.
- The private GCP dashboard returned existing CPU, memory, request and latency samples. Its 5xx
  selector returned no series for the queried window; no continuous-uptime claim is made.

Feature pipeline 2964484108 executed native SAST, IaC, secret and dependency scans and ingested
their findings. Python/npm CycloneDX artifacts were verified. Its native policy blocked one High
advisory in development dependency `braces@3.0.3`; subsequent RAG evaluation was correctly not
run at that source. The remediation replaces the pinned Next lint plugin's glob dependency,
removing the vulnerable chain and adding six checks of real root discovery and lint enforcement.
[MR !9](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/merge_requests/9)
records exact-source CI results. Protected-main image scans cannot be verified from a feature
branch. New JUnit totals must be checked in the final source pipeline; the first run exposed
frontend report deduplication/cleanup, which the follow-up configuration corrects. Human merge
and production promotion remain separate.

## Existing corpus and provider evidence

Earlier ingestion and evaluation evidence established seven completed FAERS releases from 2024Q4
through 2026Q2, 39 PubMed documents and six archived DailyMed versions, with 561 canonical chunks.
2026Q3 is absent. This is a bounded corpus, not complete literature or label history. Full-population
metrics matched independent SQL for the reviewed cutoffs. Runtime canonical data permissions were
read-only; ingestion/evaluation used separate identities. Both pinned MedCPT encoders produced
768-dimensional vectors.

Earlier live checks exercised Vertex and fallback providers and a ten-case semantic judge;
those are not fresh provider checks for the operations branch. Live judging supplements reviewed
ground truth and never establishes causality. The historical top_k=1 rehearsals failed the frozen
gate; the separately planned hosted Duo regression-to-repair demonstration is still pending.

No counts, answers, citations or benchmark expectations are fabricated to bridge pending work.
