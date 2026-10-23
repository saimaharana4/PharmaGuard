# Security and governance

- Cloud credentials use GitLab-to-GCP Workload Identity Federation restricted to the official
  project and protected deployment branch. No downloadable service-account keys.
- Secret Manager supplies API keys, database credentials and provider configuration. No `.env`
  files or secret values are published in source, Wiki, reports or artifacts.
- API access stays private. Anonymous web sessions use secure cookies, request validation,
  origin checks and a shared usage cap. Anonymous access is not an authenticated user boundary.
- Runtime canonical data is read-only. Ingestion and evaluation have separate identities.
- Logs use allowlisted operational fields; prompts, answers and tokens are excluded.
- Existing Python, web dependency and secret audits block failed releases. Native SAST, IaC,
  secret and dependency scans executed in feature pipeline 2964484108; actual native findings
  and Python/npm SBOMs were retrieved and verified. Protected-main container scans remain pending.
- Full Terraform plans retain restricted access; public evidence contains sanitized summaries.

Production approval and merges belong to a human. Staging source, readiness, digests, required
citations and latency gates must pass first. AI synthesis does not compute safety metrics.
The deterministic benchmark has fixed, reviewed ground truth. Live judging does not replace it.

Native GitLab security reports, dependency inventory and test widgets should be inspected for
the exact source pipeline. An empty vulnerability page alone does not establish a clean scan.
No scan findings are suppressed to make a demonstration pass.

The initial native policy correctly blocked a High advisory in development dependency
`braces@3.0.3` (GHSA-vfj7-8cjw-p6xm). There was no patched upstream release. The remediation
replaces the pinned Next lint plugin's `fast-glob` dependency with `tinyglobby@0.2.17`, removing
the `micromatch` / `braces` chain while retaining all lint rules. Regression tests exercise real
root discovery and detection of invalid links/images. No finding is suppressed or downgraded.
[MR !9](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/merge_requests/9)
records the exact-source scan and test results and current review status. Other reported
findings remain visible. Production stays on the approved baseline until human promotion.

Hosted Observability, integrations requiring additional credentials, and unavailable admin-only
features are intentionally excluded. Existing private GCP telemetry is used instead.
