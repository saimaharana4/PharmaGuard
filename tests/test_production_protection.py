import io
import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ci import protect_production, verify_served_source, vm_manifest
from tests.test_vm_channels import complete


@pytest.fixture
def public(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_URL", "https://pharmaguard-web-dfthmgvvaa-el.a.run.app")
    response = {"git_sha": "a" * 40, "app_version": "test-only"}

    class Connection:
        def __init__(self, host, timeout):
            assert host == "pharmaguard-web-dfthmgvvaa-el.a.run.app"
            assert timeout == 30

        def request(self, method, path):
            assert (method, path) == ("GET", "/api/version")

        def getresponse(self):
            body = io.BytesIO(json.dumps(response).encode())
            body.status = 200
            return body

        def close(self):
            pass

    monkeypatch.setattr(protect_production.http.client, "HTTPSConnection", Connection)
    return tmp_path, response


def test_production_source_must_remain_unchanged(public):
    root, response = public
    protect_production.capture("before", root)
    protect_production.capture("after", root)
    assert json.loads((root / "production-after.json").read_text()) == response
    response["git_sha"] = "b" * 40
    with pytest.raises(ValueError, match="changed"):
        protect_production.capture("after", root)
    assert not (root / "production-after.json").exists()


def test_https_edge_cannot_claim_this_pipeline_when_serving_old_source(public, monkeypatch):
    root, response = public
    monkeypatch.setenv("CI_COMMIT_SHA", response["git_sha"])
    output = root / "edge-version.json"
    verify_served_source.verify(output)
    assert json.loads(output.read_text()) == response
    response["git_sha"] = "b" * 40
    with pytest.raises(ValueError, match="does not match"):
        verify_served_source.verify(output)
    assert not output.exists()


@pytest.mark.parametrize("source", ["unknown", "a" * 39, "A" * 40])
def test_unverifiable_production_removes_stale_snapshots(public, source):
    root, response = public
    protect_production.capture("before", root)
    protect_production.capture("after", root)
    response["git_sha"] = source
    with pytest.raises(ValueError, match="verifiable"):
        protect_production.capture("before", root)
    assert not (root / "production-before.json").exists()
    assert not (root / "production-after.json").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid",
        "https://user@example.invalid",
        "https://example.invalid/path",
        "https://example.invalid/#fragment",
    ],
)
def test_production_url_is_checked_before_network_access(public, monkeypatch, url):
    root, _ = public
    monkeypatch.setenv("WEB_URL", url)
    with pytest.raises(ValueError, match="HTTPS"):
        protect_production.capture("before", root)


def test_preview_smoke_does_not_overwrite_public_verification_url(tmp_path):
    """Execute the actual CI commands with dependency stubs, preserving shell scoping."""
    root = Path(__file__).resolve().parents[1]
    job = yaml.safe_load((root / ".gitlab/ci/vm.yml").read_text())["postdeploy:vm"]
    if os.name == "nt":
        bash = Path(shutil.which("git")).resolve().parent.parent / "bin/bash.exe"
    else:
        bash = shutil.which("bash")
    script = """set -euo pipefail
python3() { printf 'verify:%s:%s\\n' "$*" "$WEB_URL"; }
bash() { :; }
gcloud() { printf 'https://preview.example.invalid'; }
uv() { printf 'smoke:%s\\n' "$WEB_URL"; }
""" + "\n".join(job["script"])
    result = subprocess.run(
        [str(bash), "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "WEB_URL": "https://production.example.invalid",
            "GCP_PROJECT_ID": "test-project",
            "GCP_REGION": "test-region",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "smoke:https://preview.example.invalid" in result.stdout
    assert (
        "verify:-m ci.protect_production after:https://production.example.invalid" in result.stdout
    )


def test_expected_manifest_contains_only_reviewable_references(monkeypatch, tmp_path):
    expected = complete(2)
    for field, variable in vm_manifest.FIELDS.items():
        monkeypatch.setenv(variable, expected[field])
    monkeypatch.setenv("UNRELATED_PRIVATE_CREDENTIAL", "do-not-serialize-this")
    output = tmp_path / "manifest.json"
    vm_manifest.write(output)
    assert json.loads(output.read_text()) == expected
    assert "do-not-serialize-this" not in output.read_text()


@pytest.mark.parametrize(
    "fault", [None, "changed-production", "wrong-source", "wrong-edge", "wrong-image"]
)
def test_release_evidence_requires_protected_production_and_exact_staging(
    monkeypatch, tmp_path, fault
):
    source, image = "a" * 40, complete(2)["api_image"]
    event = {
        "event": "deployment_completed",
        "channel": "staging",
        "git_sha": source,
        "image_digest": image,
    }
    before = {"git_sha": "b" * 40, "app_version": "test-only"}
    files = {
        "vm-events.jsonl": json.dumps(event),
        "vm-ready.json": json.dumps({"status": "ready"}),
        "vm-version.json": json.dumps({"git_sha": source}),
        "edge-version.json": json.dumps({"git_sha": source}),
        "production-before.json": json.dumps(before),
        "production-after.json": json.dumps(before),
    }
    if fault == "changed-production":
        files["production-after.json"] = json.dumps({**before, "git_sha": source})
    elif fault == "wrong-source":
        files["vm-version.json"] = json.dumps({"git_sha": "c" * 40})
    elif fault == "wrong-edge":
        files["edge-version.json"] = json.dumps({"git_sha": "c" * 40})
    elif fault == "wrong-image":
        files["vm-events.jsonl"] = json.dumps({**event, "image_digest": "wrong-image"})
    directory = tmp_path / "deployment"
    directory.mkdir()
    for name, body in files.items():
        (directory / name).write_text(body)
    (tmp_path / "postdeploy-report.json").write_text('{"passed":true}')
    script = Path(__file__).resolve().parents[1] / "ci/release_evidence.py"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_COMMIT_SHA", source)
    monkeypatch.setenv("API_IMAGE", image)
    monkeypatch.setenv("CI_PIPELINE_URL", "https://example.invalid/pipeline")
    if fault:
        with pytest.raises(ValueError):
            runpy.run_path(str(script), run_name="__main__")
        assert not (directory / "release-evidence.json").exists()
    else:
        runpy.run_path(str(script), run_name="__main__")
        evidence = json.loads((directory / "release-evidence.json").read_text())
        assert evidence["production_protected"]["unchanged"] is True
