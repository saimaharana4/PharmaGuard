"""Owner recovery must use the installed controller and preserve migration boundaries."""

import sys

import pytest

from infra import deploy_vm


@pytest.mark.parametrize("action", [None, "--rollback", "--promote"])
def test_recovery_preserves_installed_controller_and_skips_migration(monkeypatch, tmp_path, action):
    arguments = [
        "deploy-vm",
        "--project",
        "test-project",
        "--api-image",
        "registry.example/test/api@sha256:" + "a" * 64,
        "--web-image",
        "registry.example/test/web@sha256:" + "b" * 64,
        "--sql-proxy-image",
        "registry.example/test/proxy@sha256:" + "c" * 64,
        "--sha",
        "d" * 40,
        "--runtime-version",
        "1",
    ]
    if action:
        arguments.append(action)
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.chdir(tmp_path)
    calls = []

    def cloud(*args):
        calls.append(args)
        return "123" if args[:3] == ("compute", "instances", "describe") else ""

    monkeypatch.setattr(deploy_vm, "gcloud", cloud)
    deploy_vm.main()
    migrations = [call for call in calls if call[:2] == ("run", "jobs")]
    controller_upload = [
        call for call in calls if call[:3] == ("compute", "scp", "infra/vm/release.py")
    ]
    assert bool(migrations) is (action is None)
    assert bool(controller_upload) is (action is None)
    ssh = next(call for call in calls if call[:2] == ("compute", "ssh"))
    command = next(arg for arg in ssh if arg.startswith("--command="))
    if action == "--promote":
        assert "release.py --promote " in command
        assert "/opt/pharmaguard/release.json" not in command
    elif action == "--rollback":
        assert "release.py --stage-rollback " in command
        assert "/opt/pharmaguard/release.json" in command
    else:
        assert "install -m 0700 ~/pg-release-controller.py" in command
