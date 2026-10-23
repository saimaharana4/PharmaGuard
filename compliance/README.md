# Dependency license evidence

The application source is MIT licensed. Dependencies retain their own licenses;
the project license does not relicense them.

GitLab ingests the native dependency scanner's CycloneDX inventories. The
`license:evidence` job adds verified exact-version declarations for packages whose
license metadata was missing from GitLab's inventory. It preserves component
identities, hashes, dependency relationships and analyzer provenance. It refuses
to overwrite a conflicting existing declaration. Other components retain their
native metadata and GitLab's license database fallback.

`license-evidence.json` records the official npm/PyPI metadata URL, SHA-256 of the
retrieved response, SPDX expression and verification date for each declaration.
When registry metadata omits the license, a reviewed upstream license file is pinned
to its release commit, with its text checksum and registry provenance recorded. Jinja2
3.1.6 uses its upstream BSD-3-Clause license text because PyPI declares no expression.
Null, empty and unrecognized expressions fail validation before SBOM publication.

These are source declarations, not legal approvals. Updating a dependency requires
verifying that exact version's metadata again; receipts never apply to another
version. The evidence is static and reviewable; CI does not fetch or invent labels.

Inspect the job's `license-summary.json`, enriched CycloneDX artifacts and GitLab
License compliance view together. An unknown license requires investigation; it
does not establish a license prohibition. LGPL and MPL declarations remain visible
and must be reviewed for the distributed artifact and applicable obligations.
No allow/deny rules, legal approvals or vulnerability dismissals are created here.

See [GitLab's CycloneDX license scanning documentation](https://docs.gitlab.com/user/compliance/license_scanning_of_cyclonedx_files/)
for report ingestion and policy behavior.
