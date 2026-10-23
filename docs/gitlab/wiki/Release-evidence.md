# Production release evidence

[PharmaGuard AI 0.1.0](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/releases/v0.1.0) identifies source `3a724e294892dce03ff89a1a0edcbe5fb2b973ff`.
[Pipeline 2964871282](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines/2964871282) passed all 32 release jobs, including packaging,
security policy, Terraform, staging, production promotion, public smoke and final governance.

| Verification | Observed result |
| --- | --- |
| Reviewed RAG benchmark | 10/10 cases; exact facts, critical evidence and zero temporal leakage |
| Staging investigation | 31.93 seconds; required citations present |
| Public investigation | 30.09 seconds; required citations present |
| Production revision | `pharmaguard-web-00013-pwh` |
| Infrastructure | 0 created, 4 updated in place, 0 destroyed; existing VM retained |
| Routing | Production retained its approved source during staging verification |
| HTTPS source | Both routes independently match the released commit |
| Approvals | Production promotion and final governance completed |

## Runtime image digests

| Image | Immutable digest |
| --- | --- |
| API | `sha256:1d66fc50c84211669d8d5d85a840457fc27b07547c4aa398148c7b8d342fda07` |
| EDGE | `sha256:fa14069b07fba0358a609085fb9ba56104ba122cfa61dab773b3ec6571ae6832` |
| WEB | `sha256:64e5055986076af6111f5a7586f8169910f948110b859bee5424c8723baab968` |

## Verification artifacts

The [release assets](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/releases/v0.1.0) contain sanitized JSON with member checksums.
Evidence ZIP SHA256: `50b730a2b8c38a027aaf27e99bc0a5287c996e52a8da6a6cda99ea7f5de7d9cf`.
Frozen dataset SHA256: `3e24ee4fb783704abcf7ea538bbf490cbe7b147d7d70ebffe52b8673a85086a1`.
The original staging artifact retains its pre-promotion state; the final manifest and
public smoke report establish completed production verification.

## Operational limitations

This dataset has a bounded evidence corpus and no 2026Q3 FAERS reports. Lower-severity
security findings remain visible in native reports. The shared VM does not provide
high availability; smoke timing is a point-in-time check rather than an uptime guarantee.

## Earlier deployment

The [earlier production pipeline](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines/2964230916) verified source
`a3eeebea0931d1c422132612cf0ceba74601b6a2` with 20 successful jobs, a 33.03-second
staging investigation and a 30.26-second public investigation. The checksum-verified
[earlier verification bundle](https://gitlab.com/api/v4/projects/87777712/packages/generic/release-evidence/a3eeebea/release-evidence.zip)
preserves the original results independently of release-page metadata.
