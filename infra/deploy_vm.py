"""Owner-operated staging release; public Cloud Run promotion remains a human CI action."""

import argparse
import json
import re
import uuid
from pathlib import Path

from infra.provision_runtime import gcloud
from infra.vm.release import validate_release


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--rollback", action="store_true", help="Stage recorded previous production"
    )
    action.add_argument(
        "--promote", action="store_true", help="Human-approved promotion of staging"
    )
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--sql-proxy-image", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--runtime-version", required=True, type=int)
    parser.add_argument("--ingest-version", default=3, type=int)
    parser.add_argument("--zone", default="asia-south1-a")
    parser.add_argument("--region", default="asia-south1")
    args = parser.parse_args()
    for image in [args.api_image, args.web_image, args.sql_proxy_image]:
        if not re.fullmatch(r"[a-z0-9.-]+/[\w./-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("Use immutable image digests")
    instance = "pharmaguard-hackathon"
    scope = ["--project=" + args.project, "--zone=" + args.zone]
    cloud = ["--project=" + args.project, "--region=" + args.region]
    config = f"projects/{args.project}/secrets"
    connection = f"{args.project}:{args.region}:pg-pharmaguard-hackathon"
    release = {
        "api_image": args.api_image,
        "web_image": args.web_image,
        "sql_proxy_image": args.sql_proxy_image,
        "git_sha": args.sha,
        "runtime_config": f"{config}/pg-config-runtime/versions/{args.runtime_version}",
        "sql_connection": connection,
        "expires_at": "2026-11-19T18:30:00Z",
    }
    validate_release(release)
    before = gcloud("compute", "instances", "describe", instance, *scope, "--format=value(id)")
    if not args.rollback and not args.promote:
        gcloud(
            "run",
            "jobs",
            "deploy",
            "pharmaguard-migrate",
            *cloud,
            "--image=" + args.api_image,
            f"--service-account=pg-ingest-sa@{args.project}.iam.gserviceaccount.com",
            "--set-cloudsql-instances=" + connection,
            f"--set-env-vars=APP_CONFIG_SECRET={config}/pg-config-ingest/versions/{args.ingest_version}",
            "--command=alembic",
            "--args=upgrade,head",
            "--max-retries=0",
            "--task-timeout=600s",
        )
        gcloud("run", "jobs", "execute", "pharmaguard-migrate", *cloud, "--wait")
    identifier = uuid.uuid4().hex
    path = Path(f".data/vm-candidate-{identifier}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(release))
    path.chmod(0o600)
    remote = f"pg-release-{identifier}.json"
    gcloud("compute", "scp", str(path), instance + ":" + remote, *scope, "--tunnel-through-iap")
    if not args.rollback and not args.promote:
        gcloud(
            "compute",
            "scp",
            "infra/vm/release.py",
            instance + ":pg-release-controller.py",
            *scope,
            "--tunnel-through-iap",
        )
    install = (
        "sudo install -m 0700 ~/pg-release-controller.py /opt/pharmaguard/release.py && "
        if not args.rollback and not args.promote
        else ""
    )
    mode = "--promote " if args.promote else "--stage-rollback " if args.rollback else ""
    candidate = "/opt/pharmaguard/" + remote
    record = (
        f" && sudo install -m 0600 {candidate} /opt/pharmaguard/release.json"
        if not args.promote
        else ""
    )
    output = gcloud(
        "compute",
        "ssh",
        instance,
        *scope,
        "--tunnel-through-iap",
        f"--command={install}sudo install -m 0600 ~/{remote} {candidate} && "
        f"sudo python3 /opt/pharmaguard/release.py {mode}{candidate}{record} && "
        f"sudo rm -f {candidate}",
    )
    after = gcloud("compute", "instances", "describe", instance, *scope, "--format=value(id)")
    if before != after:
        raise RuntimeError("Instance identity changed unexpectedly")
    Path(".data/vm-deployment-events.jsonl").write_text(output + "\n")
    print(output)
    print(json.dumps({"instance_id": after, "preserved_instance": True}))


if __name__ == "__main__":
    main()
