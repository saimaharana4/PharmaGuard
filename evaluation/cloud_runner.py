"""Run auditable evaluations beside Cloud SQL; exchange artifacts through GCS, not DB ports."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from pharmaguard.config import load_settings

from evaluation.core import file_digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["prepare", "export", "run", "judge"], required=True)
    parser.add_argument("--dataset-id")
    parser.add_argument("--version", default="v2")
    parser.add_argument("--labels-uri")
    parser.add_argument("--labels-sha256")
    parser.add_argument("--snapshot-uri", required=True)
    parser.add_argument("--report-prefix", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--top-k", type=int, choices=[1, 5])
    args = parser.parse_args()
    settings = load_settings()
    client = storage.Client(project=settings.gcp_project_id)
    directory = Path(".data/evaluation")
    directory.mkdir(parents=True, exist_ok=True)

    def blob(uri):
        parsed = urlparse(uri)
        if (
            parsed.scheme != "gs"
            or parsed.netloc != settings.gcs_bucket
            or not parsed.path.startswith("/evaluation/")
        ):
            raise ValueError(
                "Evaluation artifacts must use the configured bucket's evaluation prefix"
            )
        return client.bucket(parsed.netloc).blob(parsed.path.lstrip("/"))

    def upload(path, uri):
        target, digest = blob(uri), file_digest(path)
        target.metadata = {"sha256": digest}
        try:
            target.upload_from_filename(str(path), if_generation_match=0, checksum="auto")
        except PreconditionFailed:
            target.reload()
            if (target.metadata or {}).get("sha256") != digest:
                raise ValueError(
                    "Immutable evaluation artifact already contains different data"
                ) from None
        print(json.dumps({"artifact": uri, "sha256": digest}), flush=True)

    snapshot = directory / "snapshot.zip"
    output = directory / "report.json"
    if args.top_k:
        config = settings.retrieval().model_dump()
        config["top_k"] = args.top_k
        override = directory / "retrieval.json"
        override.write_text(json.dumps(config, indent=2) + "\n")
        os.environ["RETRIEVAL_CONFIG"] = str(override)
    if args.action == "prepare":
        if not args.labels_uri or not args.labels_sha256 or not args.dataset_id:
            raise ValueError("Preparation requires reviewed labels, their checksum, and a dataset")
        labels = directory / "labels.json"
        blob(args.labels_uri).download_to_filename(str(labels))
        if file_digest(labels) != args.labels_sha256:
            raise ValueError("Reviewed-label checksum mismatch")
        cases = directory / "reviewed-cases.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "evaluation.reference",
                "--dataset-id",
                args.dataset_id,
                "--labels",
                str(labels),
                "--output",
                str(cases),
            ],
            check=True,
        )
        from evaluation.cli import import_cases

        import_cases(args.dataset_id, cases)
        upload(cases, args.report_prefix.rstrip("/") + "/reviewed-cases.json")
    if args.action in {"prepare", "export"}:
        if not args.dataset_id:
            raise ValueError("Snapshot export requires a published dataset")
        from evaluation.cli import export

        export(args.dataset_id, args.version, snapshot)
        upload(snapshot, args.snapshot_uri)
        upload(snapshot.with_suffix(".zip.sha256"), args.snapshot_uri + ".sha256")
    else:
        blob(args.snapshot_uri).download_to_filename(str(snapshot))
        blob(args.snapshot_uri + ".sha256").download_to_filename(str(snapshot) + ".sha256")
    if args.expected_sha256 and file_digest(snapshot) != args.expected_sha256:
        raise ValueError("Frozen snapshot checksum mismatch")
    exit_code = 0
    if args.action == "judge":
        from evaluation.judge import run_judge

        passed = run_judge(snapshot, output)
        exit_code = 0 if passed else 1
    else:
        import typer

        from evaluation.cli import run

        try:
            run(snapshot, output, expected_sha256=args.expected_sha256)
        except typer.Exit as exc:
            exit_code = exc.exit_code
    upload(output, args.report_prefix.rstrip("/") + "/report.json")
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
