import json
from pathlib import Path

import pytest

from ci import vm_readiness


@pytest.fixture
def capture(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_JOB_ID", "12345")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("GCP_ZONE", "test-zone")
    monkeypatch.setenv("CI_COMMIT_SHA", "a" * 40)
    calls = []

    def install(body, failure=None, version=None):
        def fake_gcloud(*args, **kwargs):
            calls.append((args, kwargs))
            if args[1] == "scp":
                if failure:
                    raise failure
                content = (
                    json.dumps(version if version is not None else {"git_sha": "a" * 40})
                    if "pharmaguard-version-" in args[2]
                    else body
                )
                Path(args[3]).write_text(content, encoding="utf-8")
            return "Generating public/private rsa key pair.\nSSH setup log\n"

        monkeypatch.setattr(vm_readiness, "gcloud", fake_gcloud)
        return calls

    return install


def test_readiness_capture_separates_ssh_setup_output(capture):
    ready = {"status": "ready", "dataset_id": "published-dataset", "coverage": {"complete": True}}
    calls = capture(json.dumps(ready))
    vm_readiness.main()
    assert json.loads(Path("deployment/vm-ready.json").read_text()) == ready
    assert len(calls) == 4
    assert calls[1][0][2] == "pharmaguard-hackathon:/tmp/pharmaguard-ready-12345.json"
    assert all("--tunnel-through-iap" in args for args, _ in calls)
    assert json.loads(Path("deployment/vm-version.json").read_text())["git_sha"] == "a" * 40
    assert calls[-1][0][-1] == (
        "--command=rm -f -- /tmp/pharmaguard-ready-12345.json /tmp/pharmaguard-version-12345.json"
    )


@pytest.mark.parametrize("body", ["", "SSH log\n{}", "[]", '{"status":"not_ready"}'])
def test_invalid_readiness_fails_without_stale_artifact(capture, body):
    calls = capture(body)
    Path("deployment").mkdir()
    Path("deployment/vm-ready.json").write_text('{"status":"ready"}')
    with pytest.raises(ValueError):
        vm_readiness.main()
    assert not Path("deployment/vm-ready.json").exists()
    assert calls[-1][1] == {"allow_missing": True}


def test_transfer_error_preserved_and_remote_file_cleaned(capture):
    failure = RuntimeError("SCP failed")
    calls = capture("{}", failure)
    with pytest.raises(RuntimeError, match="SCP failed"):
        vm_readiness.main()
    assert not Path("deployment/vm-ready.json").exists()
    assert calls[-1][1] == {"allow_missing": True}


def test_remote_probe_failure_cannot_publish_readiness(capture, monkeypatch):
    calls = capture("{}")

    def failed_probe(*args, **kwargs):
        calls.append((args, kwargs))
        if not kwargs.get("allow_missing"):
            raise RuntimeError("Remote HTTP request failed")

    monkeypatch.setattr(vm_readiness, "gcloud", failed_probe)
    with pytest.raises(RuntimeError, match="Remote HTTP request failed"):
        vm_readiness.main()
    assert not Path("deployment/vm-ready.json").exists()
    assert len(calls) == 2
    assert calls[-1][1] == {"allow_missing": True}


def test_job_id_cannot_inject_remote_commands(capture, monkeypatch):
    calls = capture("{}")
    monkeypatch.setenv("CI_JOB_ID", "123; command")
    with pytest.raises(ValueError, match="numeric CI job ID"):
        vm_readiness.main()
    assert not calls


@pytest.mark.parametrize("version", [{"git_sha": "b" * 40}, {}, [], {"git_sha": "unknown"}])
def test_ready_but_wrong_staging_source_cannot_publish_artifacts(capture, version):
    capture('{"status":"ready"}', version=version)
    Path("deployment").mkdir()
    for name in ("vm-ready.json", "vm-version.json"):
        Path("deployment", name).write_text('{"stale":true}')
    with pytest.raises(ValueError, match="source"):
        vm_readiness.main()
    assert not Path("deployment/vm-ready.json").exists()
    assert not Path("deployment/vm-version.json").exists()
