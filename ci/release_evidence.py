"""Sanitized evidence for human/Duo review. Does not turn readiness into an answer pass."""

import json
import os
from pathlib import Path

root = Path("deployment")
events = []
for line in (root / "vm-events.jsonl").read_text().splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        continue
    events.append(
        {
            key: value
            for key, value in item.items()
            if key
            in {
                "timestamp",
                "event",
                "git_sha",
                "image_digest",
                "status",
                "slot",
                "channel",
                "error_type",
            }
        }
    )
if not any(
    item.get("event") == "deployment_completed"
    and item.get("channel") == "staging"
    and item.get("git_sha") == os.environ["CI_COMMIT_SHA"]
    and item.get("image_digest") == os.environ["API_IMAGE"]
    for item in events
):
    raise ValueError("No actual successful deployment event")
ready = json.loads((root / "vm-ready.json").read_text())
version = json.loads((root / "vm-version.json").read_text())
edge_version = json.loads((root / "edge-version.json").read_text())
if any(value.get("git_sha") != os.environ["CI_COMMIT_SHA"] for value in (version, edge_version)):
    raise ValueError("Staging source does not match this pipeline")
before = json.loads((root / "production-before.json").read_text())
after = json.loads((root / "production-after.json").read_text())
if before != after:
    raise ValueError("Production changed during staging")
if ready.get("status") != "ready":
    raise ValueError("VM readiness did not pass")
smoke = json.loads(Path("postdeploy-report.json").read_text())
if smoke.get("passed") is not True:
    raise ValueError("The reviewed staging investigation smoke did not pass")
(root / "release-evidence.json").write_text(
    json.dumps(
        {
            "git_sha": os.environ["CI_COMMIT_SHA"],
            "pipeline_url": os.environ["CI_PIPELINE_URL"],
            "events": events,
            "readiness": ready,
            "staging_version": version,
            "staging_edge_version": edge_version,
            "production_protected": {"before": before, "after": after, "unchanged": True},
            "staging_smoke": smoke,
            "public_smoke": "pending_human_promotion",
            "production_approval": "required",
        },
        indent=2,
    )
)
