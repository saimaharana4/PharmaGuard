import json
from pathlib import Path

import pytest

from infra.vm import release


def manifest(number):
    return {
        field: f"registry.example/team/{app}@sha256:{number:064x}"
        for field, app in [
            ("api_image", "api"),
            ("web_image", "web"),
            ("sql_proxy_image", "proxy"),
        ]
    }


def test_ten_releases_keep_active_and_rollback_images_only(monkeypatch):
    state = {"release": manifest(10), "previous": {"release": manifest(9)}}
    images = []
    for number in range(1, 11):
        for app in ["api", "web"]:
            images.append(
                {
                    "Repository": "registry.example/team/" + app,
                    "Digest": f"sha256:{number:064x}",
                    "ID": f"sha256:{number:064x}",
                }
            )
    foreign = {
        "Repository": "registry.example/other/app",
        "Digest": "sha256:" + "a" * 64,
        "ID": "sha256:" + "b" * 64,
    }
    images.append(foreign)
    # Multiple tags can produce duplicate repository/digest rows for one image.
    images.extend(images[:4])
    removed = []

    def command(*args):
        if args[1:3] == ("image", "ls"):
            return "\n".join(json.dumps(x) for x in images)
        if args[1:3] == ("image", "rm"):
            removed.append(args[-1])
        return ""

    monkeypatch.setattr(release, "command", command)
    monkeypatch.setattr(release, "log", lambda *a, **k: None)
    release.cleanup_images(state)
    assert len(removed) == 16
    assert not set(removed) & release.retained_images(state)
    assert not any("/other/" in x for x in removed)


def test_in_use_images_and_candidate_are_never_removed(monkeypatch):
    state = {"release": manifest(3), "previous": {"release": manifest(2)}}
    candidate = manifest(4)
    old = {
        "Repository": "registry.example/team/api",
        "Digest": "sha256:" + "1" * 64,
        "ID": "sha256:in-use",
    }
    removed = []

    def command(*args):
        if args[1:3] == ("ps", "-aq"):
            return "unrelated-container"
        if args[1] == "inspect":
            return "sha256:in-use"
        if args[1:3] == ("image", "ls"):
            return json.dumps(old)
        if args[1:3] == ("image", "rm"):
            removed.append(args[-1])
        return ""

    monkeypatch.setattr(release, "command", command)
    monkeypatch.setattr(release, "log", lambda *a, **k: None)
    release.cleanup_images(state, candidate)
    assert not removed
    assert set(candidate.values()) <= release.retained_images(state, candidate)


@pytest.mark.parametrize("failure_after_commit", [False, True])
def test_failed_candidate_cleanup_preserves_active_slot(
    monkeypatch, tmp_path, failure_after_commit
):
    def complete(number):
        return {
            **manifest(number),
            "sql_proxy_image": manifest(1)["sql_proxy_image"],
            "runtime_config": "projects/test/secrets/pg-config-runtime/versions/1",
            "sql_connection": "project:region:database",
            "git_sha": f"{number:040x}",
            "expires_at": "2100-01-01T00:00:00Z",
        }

    previous = {"slot": "blue", "release": complete(1), "previous": None}
    (tmp_path / "active.json").write_text(json.dumps(previous))
    (tmp_path / "production.json").write_text(json.dumps(previous))
    commands = []
    cleanups = 0

    def command(*args, **kwargs):
        commands.append(args)
        if args[1:3] == ("network", "ls"):
            return "pg-app"
        if args[1:3] == ("ps", "-a"):
            return "pg-sql\npg-web-blue\npg-api-blue"
        if args[1:3] == ("ps", "--format"):
            return "pg-web-blue\npg-api-blue\npg-web-green\npg-api-green"
        return ""

    def cleanup(*args, **kwargs):
        nonlocal cleanups
        cleanups += 1
        if failure_after_commit and cleanups == 2:
            raise RuntimeError("Synthetic post-commit cleanup failure")

    def ready(*args, **kwargs):
        if not failure_after_commit:
            raise RuntimeError("Synthetic readiness failure")

    def local_path(value):
        if str(value).startswith(("/run/", "/etc/")):
            return tmp_path / Path(value).name
        return Path(value)

    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "Path", local_path)
    monkeypatch.setattr(release, "command", command)
    monkeypatch.setattr(release, "wait_ready", ready)
    monkeypatch.setattr(release, "verify_release", ready)
    monkeypatch.setattr(release, "install_metadata_guard", lambda: None)
    monkeypatch.setattr(release, "cleanup_images", cleanup)
    monkeypatch.setattr(release, "require_capacity", lambda: None)
    monkeypatch.setattr(release, "metadata", lambda *args: {"access_token": "synthetic"})
    monkeypatch.setattr(release, "log", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        release.apply(complete(2))
    removed = {args[-1] for args in commands if args[1:3] == ("rm", "-f")}
    assert not any(args[1] == "stop" and args[-1].endswith("blue") for args in commands)
    assert json.loads((tmp_path / "production.json").read_text()) == previous
    if failure_after_commit:
        assert not removed
        assert json.loads((tmp_path / "active.json").read_text())["slot"] == "green"
    else:
        assert removed == {"pg-web-green", "pg-api-green"}
        assert json.loads((tmp_path / "active.json").read_text()) == previous


def test_retry_stops_only_leftover_inactive_containers(monkeypatch):
    commands = []

    def command(*args):
        commands.append(args)
        if args[1:3] == ("ps", "--format"):
            return "pg-api-blue\npg-api-green\npg-web-green\npg-sql\nunrelated"
        return ""

    monkeypatch.setattr(release, "command", command)
    release.stop_inactive({"slot": "blue", "previous": {"slot": "green"}})
    assert [args[-1] for args in commands if args[1] == "stop"] == ["pg-web-green", "pg-api-green"]


def test_capacity_guard_rejects_unsafe_overlap(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(release.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))
    monkeypatch.setattr(release, "available_memory", lambda: 3 * 1024**3)
    with pytest.raises(RuntimeError, match="memory"):
        release.require_capacity()
    monkeypatch.setattr(release, "available_memory", lambda: 6 * 1024**3)
    release.require_capacity()
    monkeypatch.setattr(release.shutil, "disk_usage", lambda _: SimpleNamespace(free=2 * 1024**3))
    with pytest.raises(RuntimeError, match="disk"):
        release.require_capacity()
