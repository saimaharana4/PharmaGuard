# Source provenance

This GitHub repository starts with a clean source snapshot of PharmaGuard AI 0.1.1.

- Canonical project: https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase
- Source commit: `20715847a6fa829864f7b5796d0f8f6c9db8fafd`
- Source branch at export: `main`
- Live version endpoint checked on 23 October 2026: application version `0.1.1`,
  source SHA `20715847a6fa829864f7b5796d0f8f6c9db8fafd`, retrieval depth `top_k: 5`.
- Demo: https://youtu.be/J2ItTcts2ek

Application code, migrations, dependency lockfiles, evaluation code, tests, Terraform,
container files and GitLab CI/Duo configuration are copied from that source commit.
Only this provenance document, the README snapshot notice and additional local-artifact
ignore patterns were added for GitHub publication. Historical release evidence in the
original documentation retains its original scope and date.

The GitHub commit identifier differs because this is a new repository with one initial
snapshot commit. GitLab history, branches and tags were not imported. Live cloud resources
and the GitLab project were not modified by this export.

Raw recordings, local caches, generated reports, evaluation snapshots, raw corpora, model
weights, credentials, Terraform state and the original GCP transcript are not included.
The final public edited demo was subsequently archived under `docs/media/`, with a cover,
checksum and README links. That documentation addition does not change application code.
Public deployment identifiers retained in the existing documentation are configuration
references, not credentials. Runtime secrets must be supplied through authorized Secret
Manager access as described in the setup guide.

## Validation boundaries

GitLab CI remains authoritative for the release. Copying source to GitHub does not
re-run image scans, cloud deployment, live-provider evaluation or production approvals.
The separate local publication report records checks actually run for this export.
