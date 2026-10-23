"""Check native analyzer evidence; keep report ingestion separate from finding policy."""

import argparse
import json
from pathlib import Path

REQUIRED = {"sast", "secret_detection", "dependency_scanning"}
SEVERITIES = {"info", "unknown", "low", "medium", "high", "critical"}


def assess(reports: list[dict], required: set[str] | None = None) -> dict:
    required = required or REQUIRED
    seen = set()
    counts = dict.fromkeys(sorted(SEVERITIES), 0)
    blocking = set()
    for report in reports:
        scan = report.get("scan", {})
        kind = scan.get("type")
        if kind not in required or scan.get("status") != "success":
            raise ValueError("Missing successful native analyzer evidence")
        seen.add(kind)
        findings = report.get("vulnerabilities")
        if not isinstance(findings, list):
            raise ValueError("Native report has no vulnerability list")
        for finding in findings:
            severity = str(finding.get("severity", "unknown")).lower()
            if severity not in SEVERITIES or not finding.get("id"):
                raise ValueError("Malformed native security finding")
            counts[severity] += 1
            if kind == "secret_detection" or severity in {"high", "critical", "unknown"}:
                blocking.add(finding["id"])
    missing = required - seen
    if missing:
        raise ValueError("Native analyzer reports missing: " + ", ".join(sorted(missing)))
    return {
        "passed": not blocking,
        "scan_types": sorted(seen),
        "severity_counts": counts,
        "blocking_findings": len(blocking),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    # Unique copies prevent two SAST artifact archives overwriting one another.
    paths = [p for p in args.directory.glob("gl-*-report.json") if p.name != "gl-sast-report.json"]
    if args.container:
        paths = [
            args.directory / f"gl-container-{component}-report.json"
            for component in ("api", "web", "edge")
        ]
        if not all(p.is_file() for p in paths):
            raise ValueError("All three immutable images require container scan reports")
    else:
        if not (args.directory / "gl-iac-report.json").is_file():
            raise ValueError("IaC analyzer evidence is required")
        code_reports = [
            p
            for p in paths
            if p.name
            not in {
                "gl-iac-report.json",
                "gl-secret-detection-report.json",
                "gl-dependency-scanning-report.json",
            }
        ]
        if not code_reports:
            raise ValueError("Source-code SAST evidence is required in addition to IaC")
    result = assess(
        [json.loads(p.read_text(encoding="utf-8")) for p in paths],
        {"container_scanning"} if args.container else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["passed"]:
        raise SystemExit("Native security policy requires finding review and remediation")


if __name__ == "__main__":
    main()
