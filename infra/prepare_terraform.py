"""Bootstrap an isolated versioned state bucket. Never use the raw-corpus bucket for state."""

import argparse
import json

from infra.provision_runtime import gcloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="asia-south1")
    args = parser.parse_args()
    number = gcloud("projects", "describe", args.project, "--format=value(projectNumber)")
    bucket = "gs://pg-tf-state-" + number
    if not gcloud(
        "storage",
        "buckets",
        "describe",
        bucket,
        "--project=" + args.project,
        "--format=value(name)",
        allow_missing=True,
    ):
        gcloud(
            "storage",
            "buckets",
            "create",
            bucket,
            "--project=" + args.project,
            "--location=" + args.region,
            "--uniform-bucket-level-access",
            "--public-access-prevention",
        )
    gcloud(
        "storage",
        "buckets",
        "update",
        bucket,
        "--project=" + args.project,
        "--versioning",
        "--public-access-prevention",
        "--uniform-bucket-level-access",
    )
    print(
        json.dumps(
            {
                "state_bucket": bucket.removeprefix("gs://"),
                "prefix": "hackathon/application-vm",
                "credentials": "ADC_or_WIF",
            }
        )
    )


if __name__ == "__main__":
    main()
