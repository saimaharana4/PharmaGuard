---
name: rag-release-safety
description: Verify a PharmaGuard release using immutable CI artifacts and preserve human approval.
---

1. Read AGENTS.md, the target MR and deployment documentation. Identify the source commit and pipeline.
2. Inspect actual validation, unit/integration/browser, security and frozen evaluation jobs. Missing or running jobs remain pending.
3. Keep the normal release path read-only with respect to source, benchmarks, tests, configuration and CI policy. Report blockers without changing gates.
4. Confirm the reviewed dataset version/checksum and exact deterministic fact agreement. CI decides whether checks pass.
5. Inspect immutable image artifacts and the policy-checked Terraform summary. Never read state, secret payloads, session tokens or environment dumps.
6. Follow existing staging job dependencies and respect every manual approval. Verify readiness and the reviewed cited investigation in postdeploy-report.json.
7. Summarize the source commit, dataset, actual job links, image digests, deployment revision, smoke result and remaining risks.
8. Ask a human to perform governance and production approval. Never merge or approve production yourself.
9. A separately requested future repair issue may authorize one bounded product/retrieval change. It never authorizes edits to labels, checksums, thresholds, tests, CI dependencies, security controls or approval jobs.
