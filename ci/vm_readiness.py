"""Capture the remote readiness file without mixing SSH setup output into JSON."""

import json
import os
import tempfile
from pathlib import Path

from infra.provision_runtime import gcloud


def main() -> None:
    job_id = os.environ["CI_JOB_ID"]
    if not job_id.isascii() or not job_id.isdecimal():
        raise ValueError("A numeric CI job ID is required")
    instance = "pharmaguard-hackathon"
    scope = [
        "--project=" + os.environ["GCP_PROJECT_ID"],
        "--zone=" + os.environ["GCP_ZONE"],
        "--tunnel-through-iap",
    ]
    remote = f"/tmp/pharmaguard-ready-{job_id}.json"
    remote_version = f"/tmp/pharmaguard-version-{job_id}.json"
    output = Path("deployment/vm-ready.json")
    version_output = Path("deployment/vm-version.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    version_output.unlink(missing_ok=True)
    try:
        # First-use gcloud SSH key generation can write to stdout. Keep the HTTP
        # body in a remote file, then transfer its bytes independently of SDK logs.
        gcloud(
            "compute",
            "ssh",
            instance,
            *scope,
            "--command=umask 077; set -C; curl --fail --silent --show-error "
            f"http://127.0.0.1:8081/api/ready > {remote} && "
            "curl --fail --silent --show-error "
            f"http://127.0.0.1:8081/api/version > {remote_version}",
        )
        with tempfile.TemporaryDirectory(prefix="pg-readiness-") as directory:
            local = Path(directory) / "ready.json"
            local_version = Path(directory) / "version.json"
            gcloud("compute", "scp", f"{instance}:{remote}", str(local), *scope)
            gcloud("compute", "scp", f"{instance}:{remote_version}", str(local_version), *scope)
            ready = json.loads(local.read_text(encoding="utf-8"))
            if not isinstance(ready, dict) or ready.get("status") != "ready":
                raise ValueError("VM readiness did not pass")
            version = json.loads(local_version.read_text(encoding="utf-8"))
            if (
                not isinstance(version, dict)
                or version.get("git_sha") != os.environ["CI_COMMIT_SHA"]
            ):
                raise ValueError("Staging source does not match this pipeline")
            output.write_text(json.dumps(ready, indent=2), encoding="utf-8")
            version_output.write_text(json.dumps(version, indent=2), encoding="utf-8")
    finally:
        gcloud(
            "compute",
            "ssh",
            instance,
            *scope,
            "--command=rm -f -- " + remote + " " + remote_version,
            allow_missing=True,
        )


if __name__ == "__main__":
    main()
