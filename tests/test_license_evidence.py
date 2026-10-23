import copy
import json
from pathlib import Path

import pytest

from ci.license_evidence import enrich, receipts


def record():
    return {
        "ecosystem": "npm",
        "name": "@test/package",
        "version": "1.2.3",
        "license_expression": "MIT",
        "source": "https://registry.npmjs.org/%40test%2Fpackage/1.2.3",
        "metadata_sha256": "a" * 64,
    }


def test_enrichment_retains_identity_dependency_graph_and_original_report():
    manifest = {"schema_version": 1, "records": [record()]}
    original = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:7b5835d3-bbd0-407a-8125-b1843751e86e",
        "version": 1,
        "components": [
            {
                "bom-ref": "stable-id",
                "purl": "pkg:npm/%40test/package@1.2.3",
                "name": "package",
                "hashes": [{"alg": "SHA-256", "content": "b" * 64}],
                "properties": [],
            }
        ],
        "dependencies": [{"ref": "stable-id", "dependsOn": []}],
    }
    before = copy.deepcopy(original)
    output, count = enrich(original, receipts(manifest))
    assert count == 1 and original == before
    assert output["dependencies"] == original["dependencies"]
    assert output["serialNumber"] == original["serialNumber"] and output["version"] == 2
    assert output["components"][0]["bom-ref"] == "stable-id"
    assert output["components"][0]["hashes"] == original["components"][0]["hashes"]
    assert output["components"][0]["licenses"] == [{"expression": "MIT"}]


def test_wrong_versions_are_never_relabelled():
    evidence = receipts({"schema_version": 1, "records": [record()]})
    bom = {
        "bomFormat": "CycloneDX",
        "components": [
            {"purl": "pkg:npm/%40test/package@2.0.0", "licenses": [{"expression": "LGPL-3.0-only"}]}
        ],
    }
    output, count = enrich(bom, evidence)
    assert count == 0 and output == bom


def test_existing_license_is_never_overwritten():
    evidence = receipts({"schema_version": 1, "records": [record()]})
    bom = {
        "bomFormat": "CycloneDX",
        "components": [
            {"purl": "pkg:npm/%40test/package@1.2.3", "licenses": [{"expression": "LGPL-3.0-only"}]}
        ],
    }
    with pytest.raises(ValueError, match="conflicts"):
        enrich(bom, evidence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "https://example.invalid/package"),
        ("license_expression", "unknown"),
        ("license_expression", None),
        ("license_expression", ""),
        ("license_expression", "  "),
        ("license_expression", 1),
        ("metadata_sha256", "missing"),
    ],
)
def test_unverified_license_receipts_fail_closed(field, value):
    entry = record()
    entry[field] = value
    with pytest.raises(ValueError):
        receipts({"schema_version": 1, "records": [entry]})


def test_reviewed_manifest_and_upstream_license_provenance():
    manifest = json.loads(Path("compliance/license-evidence.json").read_text(encoding="utf-8"))
    evidence = receipts(manifest)
    bom = {
        "bomFormat": "CycloneDX",
        "components": [{"purl": "pkg:pypi/jinja2@3.1.6"}],
    }
    output, count = enrich(bom, evidence)
    assert count == 1
    assert output["components"][0]["licenses"] == [{"expression": "BSD-3-Clause"}]
    properties = {p["name"]: p["value"] for p in output["components"][0]["properties"]}
    assert properties["pharmaguard:license:source"].endswith(
        "/15206881c006c79667fe5154fe80c01c65410679/LICENSE.txt"
    )
    assert properties["pharmaguard:license:text-sha256"]
    broken = copy.deepcopy(manifest)
    entry = next(r for r in broken["records"] if r["name"] == "jinja2")
    entry["license_source"] = "https://example.invalid/LICENSE.txt"
    with pytest.raises(ValueError, match="provenance"):
        receipts(broken)
