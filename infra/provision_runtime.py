"""Idempotent least-privilege setup for build and web identities. No secret values accessed."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def gcloud(*args: str, allow_missing: bool = False) -> str:
    executable = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
    )
    command = str(executable) if executable.is_file() else "gcloud"
    result = subprocess.run(
        [command, *args, "--quiet"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode and not allow_missing:
        raise RuntimeError("GCP setup operation failed: " + result.stderr[-1500:])
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="asia-south1")
    args = parser.parse_args()
    project = args.project
    for name in ["pg-web-sa", "pg-build-sa"]:
        email = f"{name}@{project}.iam.gserviceaccount.com"
        if not gcloud(
            "iam",
            "service-accounts",
            "describe",
            email,
            "--project=" + project,
            "--format=value(email)",
            allow_missing=True,
        ):
            gcloud("iam", "service-accounts", "create", name, "--project=" + project)
    build = f"serviceAccount:pg-build-sa@{project}.iam.gserviceaccount.com"
    gcloud(
        "artifacts",
        "repositories",
        "add-iam-policy-binding",
        "pharmaguard-hackathon",
        "--project=" + project,
        "--location=" + args.region,
        "--member=" + build,
        "--role=roles/artifactregistry.writer",
    )
    gcloud(
        "storage",
        "buckets",
        "add-iam-policy-binding",
        f"gs://pharmaguard-hackathon-{project}",
        "--project=" + project,
        "--member=" + build,
        "--role=roles/storage.objectViewer",
    )
    gcloud(
        "projects",
        "add-iam-policy-binding",
        project,
        "--member=" + build,
        "--role=roles/logging.logWriter",
        "--condition=None",
    )
    gcloud(
        "projects",
        "add-iam-policy-binding",
        project,
        f"--member=serviceAccount:pg-runtime-sa@{project}.iam.gserviceaccount.com",
        "--role=roles/aiplatform.user",
        "--condition=None",
    )
    gcloud(
        "iam",
        "service-accounts",
        "add-iam-policy-binding",
        f"pg-web-sa@{project}.iam.gserviceaccount.com",
        "--project=" + project,
        f"--member=serviceAccount:pg-gitlab-deploy-sa@{project}.iam.gserviceaccount.com",
        "--role=roles/iam.serviceAccountUser",
    )
    print(
        json.dumps(
            {"status": "configured", "web_identity": "pg-web-sa", "build_identity": "pg-build-sa"}
        )
    )


if __name__ == "__main__":
    main()
