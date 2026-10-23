"""Deploy a scoped Cloud Run evaluation job using immutable application artifacts."""

import argparse
import json
from pathlib import Path

from infra.provision_runtime import gcloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="asia-south1")
    parser.add_argument("--image", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--config-version", type=int, required=True)
    parser.add_argument("--config-secret", default="pg-config-evaluation")
    parser.add_argument("--action", choices=["prepare", "export", "run", "judge"], required=True)
    parser.add_argument("--dataset-id")
    parser.add_argument("--labels-uri")
    parser.add_argument("--labels-sha256")
    parser.add_argument("--snapshot-uri", required=True)
    parser.add_argument("--report-prefix", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--top-k", choices=["1", "5"])
    args = parser.parse_args()
    if "@sha256:" not in args.image or args.config_version < 1:
        raise ValueError("An immutable image digest and pinned configuration version are required")
    container_args = [
        "-m",
        "evaluation.cloud_runner",
        "--action",
        args.action,
        "--snapshot-uri",
        args.snapshot_uri,
        "--report-prefix",
        args.report_prefix,
    ]
    for field in ["dataset_id", "labels_uri", "labels_sha256", "expected_sha256", "top_k"]:
        value = getattr(args, field)
        if value is not None:
            container_args.extend(["--" + field.replace("_", "-"), value])
    project, region = args.project, args.region
    scope = ["--project=" + project, "--region=" + region]
    gcloud(
        "run",
        "jobs",
        "deploy",
        "pharmaguard-evaluate",
        *scope,
        "--image=" + args.image,
        f"--service-account=pg-eval-sa@{project}.iam.gserviceaccount.com",
        f"--set-cloudsql-instances={project}:{region}:pg-pharmaguard-hackathon",
        f"--set-env-vars=APP_CONFIG_SECRET=projects/{project}/secrets/{args.config_secret}/versions/"
        f"{args.config_version},GIT_SHA={args.sha},OMP_NUM_THREADS=2,MKL_NUM_THREADS=2,HF_HUB_OFFLINE=1",
        "--cpu=2",
        "--memory=8Gi",
        "--tasks=1",
        "--parallelism=1",
        "--max-retries=0",
        "--task-timeout=3600s",
        "--command=python",
        "--args=" + ",".join(container_args),
    )
    result = json.loads(
        gcloud("run", "jobs", "execute", "pharmaguard-evaluate", *scope, "--async", "--format=json")
    )
    name = result["metadata"]["name"]
    Path(f".data/cloud-evaluation-{args.action}.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps({"execution": name, "action": args.action, "report_prefix": args.report_prefix}),
        flush=True,
    )


if __name__ == "__main__":
    main()
