"""Owner bootstrap deployment: private API, public web, and an explicit ingestion job."""

import argparse
import json
from pathlib import Path

from infra.provision_runtime import gcloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="asia-south1")
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--release-manifest", required=True)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--ingest-dataset-id")
    parser.add_argument("--recover-interrupted", action="store_true")
    parser.add_argument("--runtime-config-version", type=int, required=True)
    parser.add_argument("--ingest-config-version", type=int, required=True)
    args = parser.parse_args()
    if args.recover_interrupted and not args.ingest_dataset_id:
        raise ValueError("Interrupted recovery requires the existing staging dataset ID")
    if any("@sha256:" not in image for image in [args.api_image, args.web_image]):
        raise ValueError("Deploy immutable image digests")
    project, region = args.project, args.region
    scope = ["--project=" + project, "--region=" + region]
    runtime = f"pg-runtime-sa@{project}.iam.gserviceaccount.com"
    ingest = f"pg-ingest-sa@{project}.iam.gserviceaccount.com"
    web = f"pg-web-sa@{project}.iam.gserviceaccount.com"
    connection = f"{project}:{region}:pg-pharmaguard-hackathon"
    prefix = f"projects/{project}/secrets"
    if min(args.runtime_config_version, args.ingest_config_version) < 1:
        raise ValueError("Pinned positive configuration versions are required")
    cloud_config = (
        f"APP_CONFIG_SECRET={prefix}/pg-config-runtime/versions/{args.runtime_config_version},"
        f"GIT_SHA={args.sha}"
    )
    cpu_config = ",OMP_NUM_THREADS=2,MKL_NUM_THREADS=2,HF_HUB_OFFLINE=1"
    cloud_config += cpu_config
    ingest_config = (
        f"APP_CONFIG_SECRET={prefix}/pg-config-ingest/versions/{args.ingest_config_version}"
        + cpu_config
    )
    print("Deploying migration job", flush=True)
    gcloud(
        "run",
        "jobs",
        "deploy",
        "pharmaguard-migrate",
        *scope,
        "--image=" + args.api_image,
        "--service-account=" + ingest,
        "--set-cloudsql-instances=" + connection,
        "--set-env-vars=" + ingest_config,
        "--command=alembic",
        "--args=upgrade,head",
        "--max-retries=0",
        "--task-timeout=600s",
    )
    gcloud("run", "jobs", "execute", "pharmaguard-migrate", *scope, "--wait")
    print("Deploying private API", flush=True)
    gcloud(
        "run",
        "deploy",
        "pharmaguard-api",
        *scope,
        "--image=" + args.api_image,
        "--service-account=" + runtime,
        "--add-cloudsql-instances=" + connection,
        "--set-env-vars=" + cloud_config,
        "--cpu=2",
        "--memory=4Gi",
        "--concurrency=1",
        "--min=0",
        "--max=3",
        "--timeout=90",
        "--no-allow-unauthenticated",
    )
    api_url = gcloud(
        "run", "services", "describe", "pharmaguard-api", *scope, "--format=value(status.url)"
    )
    gcloud(
        "run",
        "services",
        "add-iam-policy-binding",
        "pharmaguard-api",
        *scope,
        "--member=serviceAccount:" + web,
        "--role=roles/run.invoker",
    )
    print("Deploying anonymous web workspace", flush=True)
    gcloud(
        "run",
        "deploy",
        "pharmaguard-web",
        *scope,
        "--image=" + args.web_image,
        "--service-account=" + web,
        "--set-env-vars=API_INTERNAL_URL=" + api_url + ",API_AUTH_MODE=cloudrun",
        "--cpu=1",
        "--memory=512Mi",
        "--min=0",
        "--max=3",
        "--timeout=120",
        "--allow-unauthenticated",
    )
    web_url = gcloud(
        "run", "services", "describe", "pharmaguard-web", *scope, "--format=value(status.url)"
    )
    print("Deploying ingestion job", flush=True)
    ingest_arguments = "run"
    if args.ingest_dataset_id:
        ingest_arguments += ",--dataset-id," + args.ingest_dataset_id
    if args.recover_interrupted:
        ingest_arguments += ",--recover-interrupted"
    gcloud(
        "run",
        "jobs",
        "deploy",
        "pharmaguard-ingest",
        *scope,
        "--image=" + args.api_image,
        "--service-account=" + ingest,
        "--set-cloudsql-instances=" + connection,
        "--set-env-vars=" + ingest_config + ",FAERS_RELEASE_MANIFEST=" + args.release_manifest,
        "--cpu=2",
        "--memory=8Gi",
        "--tasks=1",
        "--parallelism=1",
        "--max-retries=0",
        "--task-timeout=86400s",
        "--command=pharmaguard-ingest",
        "--args=" + ingest_arguments,
    )
    Path(".data/cloud-deployment.json").write_text(
        json.dumps(
            {
                "api_url": api_url,
                "web_url": web_url,
                "api_image": args.api_image,
                "web_image": args.web_image,
                "git_sha": args.sha,
            },
            indent=2,
        )
    )
    print(json.dumps({"api_url": api_url, "web_url": web_url}), flush=True)
    if args.ingest:
        gcloud("run", "jobs", "execute", "pharmaguard-ingest", *scope, "--async")
        print("Ingestion execution started", flush=True)


if __name__ == "__main__":
    main()
