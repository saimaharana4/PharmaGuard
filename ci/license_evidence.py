"""Enrich SBOMs with verified license declarations, never license approvals."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from license_expression import get_spdx_licensing
from packageurl import PackageURL

UPSTREAM_LICENSE_REPOSITORIES = {("pypi", "jinja2"): "pallets/jinja"}


def key(ecosystem: str, name: str, version: str) -> tuple[str, str, str]:
    if ecosystem == "pypi":
        name = re.sub(r"[-_.]+", "-", name).lower()
    return ecosystem, name, version


def receipts(manifest: dict) -> dict:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported license evidence format")
    result = {}
    licensing = get_spdx_licensing()
    for record in manifest["records"]:
        ecosystem, name, version = (record[k] for k in ("ecosystem", "name", "version"))
        if ecosystem not in {"npm", "pypi"}:
            raise ValueError("Unsupported license registry")
        expected = (
            "https://registry.npmjs.org/" + quote(name, safe="") + "/" + quote(version, safe="")
            if ecosystem == "npm"
            else "https://pypi.org/pypi/"
            + quote(name, safe="")
            + "/"
            + quote(version, safe="")
            + "/json"
        )
        if record["source"] != expected or not re.fullmatch(
            r"[a-f0-9]{64}", record["metadata_sha256"]
        ):
            raise ValueError("License evidence must reference exact official registry metadata")
        expression = record["license_expression"]
        if (
            not isinstance(expression, str)
            or not expression.strip()
            or licensing.validate(expression, strict=True).errors
        ):
            raise ValueError("License declaration is not a recognized SPDX expression")
        if record.get("license_source") or record.get("license_text_sha256"):
            repository = UPSTREAM_LICENSE_REPOSITORIES.get(key(ecosystem, name, version)[:2])
            prefix = f"https://raw.githubusercontent.com/{repository}/"
            if (
                not repository
                or not re.fullmatch(
                    re.escape(prefix) + r"[a-f0-9]{40}/LICENSE\.txt",
                    record.get("license_source", ""),
                )
                or not re.fullmatch(r"[a-f0-9]{64}", record.get("license_text_sha256", ""))
            ):
                raise ValueError("Upstream license text must have pinned reviewed provenance")
        identity = key(ecosystem, name, version)
        if identity in result:
            raise ValueError("Duplicate license evidence")
        result[identity] = record
    return result


def enrich(sbom: dict, evidence: dict) -> tuple[dict, int]:
    result, applied = copy.deepcopy(sbom), 0
    if result.get("bomFormat") != "CycloneDX":
        raise ValueError("Expected a native CycloneDX report")
    for component in result.get("components", []):
        purl = PackageURL.from_string(component["purl"])
        name = (purl.namespace + "/" if purl.namespace else "") + purl.name
        record = evidence.get(key(purl.type, name, purl.version))
        if not record:
            continue
        declared = [{"expression": record["license_expression"]}]
        if component.get("licenses") and component["licenses"] != declared:
            raise ValueError("Registry evidence conflicts with an existing SBOM declaration")
        component["licenses"] = declared
        component.setdefault("properties", []).extend(
            [
                {
                    "name": "pharmaguard:license:source",
                    "value": record.get("license_source", record["source"]),
                },
                {"name": "pharmaguard:license:metadata-sha256", "value": record["metadata_sha256"]},
            ]
        )
        if record.get("license_source"):
            component["properties"].extend(
                [
                    {"name": "pharmaguard:license:registry-source", "value": record["source"]},
                    {
                        "name": "pharmaguard:license:text-sha256",
                        "value": record["license_text_sha256"],
                    },
                ]
            )
        applied += 1
    if applied:
        # Preserve the original BOM identity and publish its enriched revision.
        result["version"] = int(result.get("version", 1)) + 1
    return result, applied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("compliance/license-evidence.json"))
    parser.add_argument("--input", type=Path, default=Path("sca-artifacts"))
    parser.add_argument("--output", type=Path, default=Path(".data/license-sboms"))
    args = parser.parse_args()
    source = args.evidence.read_bytes()
    evidence = receipts(json.loads(source))
    summary = {
        "evidence_sha256": hashlib.sha256(source).hexdigest(),
        "reports": [],
        "license_approvals": "none; verified source declarations only",
    }
    for path in sorted(args.input.rglob("gl-sbom-*.cdx.json")):
        if path.is_symlink():
            raise ValueError("Linked SBOM inputs are not accepted")
        original = json.loads(path.read_text(encoding="utf-8"))
        result, count = enrich(original, evidence)
        target = args.output / path.relative_to(args.input)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        summary["reports"].append(
            {
                "file": str(path),
                "components": len(result["components"]),
                "verified_license_declarations_supplied": count,
            }
        )
    if not summary["reports"]:
        raise ValueError("Native dependency SBOM inputs are missing")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "license-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
