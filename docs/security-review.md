# Security remediation and release review

Native scans and application checks serve different purposes. A successful scanner
job means its report was produced; the policy jobs decide whether findings block
release. High, Critical and Unknown vulnerabilities block, and every secret finding
blocks. The image policy requires successful reports for all three packaged digests.
No finding threshold, benchmark label or production approval is relaxed.

## Remediation

- Production-protection probes accept only the two approved Cloud Run HTTPS origins,
  use a fixed path and reject redirects. VM readiness probes connect directly to
  approved loopback ports and fixed paths. Metadata credentials use only the fixed
  Google metadata host, token path and Metadata-Flavor protocol.
- All Compose services drop capabilities and prohibit privilege escalation. PostgreSQL
  runs as its image's database user. PostgreSQL, Qdrant, API and web have real health
  checks; the migration service is a one-shot command, so its health check is disabled.
- API and web runtime images use nonroot distroless Debian 13 bases, removing unused
  OS utilities, shells and package managers. Build stages retain the usual tooling.
  The final images still undergo the same vulnerability scans.
- Python remains 3.12 and retains its pinned CPU dependencies and MedCPT revisions.
  `infra/images/python_runtime.py` includes required native libraries with their
  Debian package metadata and copyright notices so scanners can identify them.
  Updated SQLite/LZMA packages are installed before assembly. Terminal/Tk extensions
  and the optional system UUID extension are excluded; standard UUID generation
  continues to use OS randomness. The API, migration and ingestion entry points
  execute directly without a shell, and the HTTP listener uses port 8080.
- The web runtime includes standalone application output and Node 24, with application
  code owned by root and only the Next.js cache owned by the runtime user. Next's
  lint presets remain enabled. Ajv's URI resolver is replaced by maintained fast-uri
  through a pinned dependency override, with schema/reference compatibility checks.
- Retry jitter uses the standard library's secrets module. VPC flow logs use 10%
  sampling and a ten-minute aggregation interval with extra metadata excluded.
  Terraform resource identities and deletion protection remain unchanged.
- Exact-version license evidence supplements the SBOMs; it never approves licenses
  or removes LGPL/MPL declarations. See [the compliance notes](../compliance/README.md).

## Findings that require context

The VM's `cloud-platform` OAuth scope remains intentional. Google recommends this
scope combined with least-privilege IAM; narrowing it would not substitute for IAM
and could break Secret Manager/Vertex access. Runtime IAM and pinned secret versions
remain the authorization boundaries. See [Google's service account guidance](https://docs.cloud.google.com/compute/docs/access/service-accounts).

Local named database/vector volumes preserve data. The shared ADC mount is read-only
and is used only for local authenticated development; no credential is built into
an image. Retained findings stay in the native reports. These explanations are not
scanner exclusions or vulnerability dismissals.

The dependency-install line uses pnpm 12.14.0 and its frozen lockfile. A generic IaC
rule can misclassify `pnpm install --frozen-lockfile` as an unpinned npm installation;
both the package manager version and resolved dependency versions are pinned.
Native runtime library upgrades are pinned to the verified Debian security versions.

## Verification and promotion

Review source tests, real PostgreSQL/Qdrant integration, routing isolation, frontend
tests, frozen RAG results, native reports and license evidence in the repair pipeline.
Runtime images must also build, start and pass the unchanged image policy against
their exact packaged digests on protected main. Distroless removes shell-based
debugging: use application logs and direct Python/Node commands instead.

Human review is required before merge, Terraform application and production
promotion. A failed main image policy blocks deployment; it does not invalidate the
last approved production revision or authorize replacing it automatically.

Runtime design references: [Distroless supported images and behavior](https://github.com/GoogleContainerTools/distroless),
[official Python images](https://hub.docker.com/_/python),
[official Node images](https://github.com/nodejs/docker-node).
