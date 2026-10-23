"""Package only selected, validated release evidence; never upload raw job traces or state."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

from ci.test_reports import rag_junit
from operations.workspace import SNAPSHOT_SHA256, SOURCE

FILES = (
    "final-pipeline.json",
    "rag.json",
    "staging-smoke.json",
    "public-smoke.json",
    "release-evidence.json",
    "staging-edge-version.json",
    "public-edge-version.json",
    "package-digests.json",
    "production-deployment.json",
    "production-browser.json",
    "independent-vm-routing.json",
    "independent-https-sources.json",
    "fresh-terraform-summary.json",
)
FORBIDDEN_KEYS = {
    "password",
    "access_token",
    "refresh_token",
    "private_key",
    "client_secret",
    "authorization",
    "api_key",
    "secret_payload",
    "jwt",
}
TOKEN = re.compile(
    r"(?:glpat-|gsk_|sk-proj-)[A-Za-z0-9_-]{12,}|"
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)


def reject_secrets(value) -> None:
    if isinstance(value, dict):
        if FORBIDDEN_KEYS.intersection(str(key).lower() for key in value):
            raise ValueError("Credential-like key is not permitted in release evidence")
        for child in value.values():
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
    elif isinstance(value, str) and TOKEN.search(value):
        raise ValueError("Credential-like value is not permitted in release evidence")


def bundle(directory: Path, output: Path) -> str:
    records = {}
    for name in FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            raise ValueError(f"Missing, oversized or linked evidence file: {name}")
        records[name] = json.loads(path.read_text(encoding="utf-8"))
        reject_secrets(records[name])
    pipeline = records["final-pipeline.json"]
    if pipeline["sha"] != SOURCE or pipeline["status"] != "success":
        raise ValueError("Release pipeline is not the verified source")
    if len(pipeline["jobs"]) != 20 or any(j["status"] != "success" for j in pipeline["jobs"]):
        raise ValueError("Expected twenty successful release jobs")
    rag = records["rag.json"]
    rag_junit(rag)
    if (
        rag["git_sha"] != SOURCE
        or rag["snapshot_sha256"] != SNAPSHOT_SHA256
        or len(rag["cases"]) != 10
        or not rag["passed"]
    ):
        raise ValueError("Frozen benchmark evidence does not match release")
    for name in ("staging-smoke.json", "public-smoke.json"):
        smoke = records[name]
        if (
            smoke["git_sha"] != SOURCE
            or smoke["passed"] is not True
            or not 0 < smoke["duration_seconds"] < 60
            or not smoke["checks"]["citation_ids"]
        ):
            raise ValueError("Missing successful bounded cited investigation")
    output.parent.mkdir(parents=True, exist_ok=True)
    members = {
        name: (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
        for name, data in records.items()
    }
    members["checksums.json"] = json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
        sort_keys=True,
        indent=2,
    ).encode()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(digest + "\n", encoding="utf-8")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(bundle(args.directory, args.output))


if __name__ == "__main__":
    main()
