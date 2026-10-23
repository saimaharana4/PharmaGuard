import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.vm import release
from tests.test_vm_retention import manifest


def complete(number):
    return {
        **manifest(number),
        "sql_proxy_image": manifest(1)["sql_proxy_image"],
        "runtime_config": "projects/test/secrets/pg-config-runtime/versions/1",
        "sql_connection": "project:region:database",
        "git_sha": f"{number:040x}",
        "expires_at": "2100-01-01T00:00:00Z",
    }


@pytest.fixture
def host(monkeypatch, tmp_path):
    production = {"schema_version": 2, "slot": "blue", "release": complete(1), "previous": None}
    for name in ("active.json", "production.json"):
        (tmp_path / name).write_text(json.dumps(production))
    config = tmp_path / "pharmaguard"
    config.write_text(release.route_config("blue", "blue"))
    containers = {
        "pg-api-blue": complete(1)["api_image"],
        "pg-web-blue": complete(1)["web_image"],
        "pg-sql": complete(1)["sql_proxy_image"],
    }
    running = set(containers)
    calls = []
    state = SimpleNamespace(
        root=tmp_path,
        config=config,
        containers=containers,
        running=running,
        calls=calls,
        fail_candidate=False,
        fail_production=False,
        fail_nginx=False,
        peak_apps=2,
    )

    def command(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("docker", "network", "ls"):
            return "pg-app"
        if args[:2] == ("nginx", "-t") and state.fail_nginx:
            state.fail_nginx = False
            raise RuntimeError("Synthetic invalid candidate configuration")
        if args[:2] == ("docker", "ps"):
            return "\n".join(sorted(containers if "-a" in args or "-aq" in args else running))
        if args[:2] == ("docker", "run"):
            name = args[args.index("--name") + 1]
            containers[name] = args[-1]
            running.add(name)
        if args[:2] == ("docker", "start"):
            assert args[-1] in containers
            running.add(args[-1])
        if args[:2] == ("docker", "stop"):
            running.discard(args[-1])
        if args[:3] == ("docker", "rm", "-f"):
            running.discard(args[-1])
            containers.pop(args[-1], None)
        if args[:2] == ("docker", "inspect"):
            return containers[args[-1]]
        state.peak_apps = max(state.peak_apps, len(running - {"pg-sql"}))
        return ""

    def verify(port, expected, **kwargs):
        listener = port
        if port in (8080, 8081):
            found = re.search(
                rf"listen {port};[^\n]*proxy_pass http://127\.0\.0\.1:(\d+)", config.read_text()
            )
            if not found:
                raise RuntimeError("No approved route")
            port = int(found[1])
        slot = "blue" if port == 28080 else "green"
        if state.fail_candidate and expected["git_sha"] != complete(1)["git_sha"]:
            raise RuntimeError("Synthetic unhealthy candidate")
        if state.fail_production and listener == 8080:
            if expected["git_sha"] != complete(1)["git_sha"]:
                raise RuntimeError("Synthetic production health failure")
        for component, field in [("api", "api_image"), ("web", "web_image")]:
            name = f"pg-{component}-{slot}"
            if name not in running or containers.get(name) != expected[field]:
                raise RuntimeError("Served fixture does not match release")

    def local_path(value):
        if str(value).startswith(("/run/", "/etc/")):
            return tmp_path / Path(value).name
        return Path(value)

    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "Path", local_path)
    monkeypatch.setattr(release, "command", command)
    monkeypatch.setattr(release, "verify_release", verify)
    monkeypatch.setattr(release, "install_metadata_guard", lambda: None)
    monkeypatch.setattr(release, "require_capacity", lambda: None)
    monkeypatch.setattr(release, "cleanup_images", lambda *a, **k: None)
    monkeypatch.setattr(release, "metadata", lambda *a: {"access_token": "synthetic"})
    monkeypatch.setattr(release, "log", lambda *a, **k: None)
    state.verify = verify
    return state


def test_ten_staging_updates_never_replace_or_stop_production(host):
    pinned = (host.root / "production.json").read_bytes()
    production_route = host.config.read_text().splitlines()[0]
    for number in range(2, 12):
        release.apply(complete(number))
        assert (host.root / "production.json").read_bytes() == pinned
        assert host.config.read_text().splitlines()[0] == production_route
        host.verify(8080, complete(1))
        host.verify(8081, complete(number))
    assert host.peak_apps == 4
    assert not any(c[:2] == ("docker", "stop") and c[-1].endswith("blue") for c in host.calls)
    assert not any(c[:3] == ("docker", "rm", "-f") and c[-1].endswith("blue") for c in host.calls)


def test_failed_staging_candidate_preserves_the_production_pin_and_route(host):
    pin = (host.root / "production.json").read_bytes()
    config = host.config.read_text()
    host.fail_candidate = True
    with pytest.raises(RuntimeError, match="unhealthy"):
        release.apply(complete(2))
    assert (host.root / "production.json").read_bytes() == pin
    assert host.config.read_text() == config
    assert not any(n.endswith("green") for n in host.containers)
    host.verify(8080, complete(1))


def test_stale_approval_cannot_promote_a_replaced_staging_release(host):
    release.apply(complete(2))
    release.apply(complete(3))
    config = host.config.read_text()
    with pytest.raises(ValueError, match="stale"):
        release.promote(complete(2))
    assert host.config.read_text() == config
    host.verify(8080, complete(1))


@pytest.mark.parametrize("component", ["api", "web"])
def test_promotion_rejects_changed_container_digests(host, component):
    release.apply(complete(2))
    host.containers[f"pg-{component}-green"] = "unexpected-image"
    with pytest.raises(RuntimeError, match="digest"):
        release.promote(complete(2))
    host.verify(8080, complete(1))


def test_failed_promotion_restores_production_without_discarding_staging(host):
    release.apply(complete(2))
    pin = (host.root / "production.json").read_bytes()
    config = host.config.read_text()
    host.fail_production = True
    with pytest.raises(RuntimeError, match="production health"):
        release.promote(complete(2))
    assert (host.root / "production.json").read_bytes() == pin
    assert host.config.read_text() == config
    host.verify(8080, complete(1))
    host.fail_production = False
    host.verify(8081, complete(2))


def test_promotion_is_idempotent_and_retains_previous_production(host):
    release.apply(complete(2))
    release.promote(complete(2))
    promoted = release.read_state("production.json")
    assert promoted["release"] == complete(2)
    assert promoted["previous"]["release"] == complete(1)
    assert host.running == {"pg-sql", "pg-api-green", "pg-web-green"}
    release.promote(complete(2))
    assert release.read_state("production.json") == promoted


def test_unapproved_isolated_staging_is_never_bootstrapped_as_production(host):
    (host.root / "production.json").unlink()
    host.config.write_text(release.route_config("blue", None))
    release.initialize_channels()
    assert not (host.root / "production.json").exists()
    assert not host.calls
    assert "return 503" in host.config.read_text().splitlines()[0]


def test_legacy_initialization_pins_existing_source_without_deploying_containers(host):
    (host.root / "production.json").unlink()
    stage = release.read_state("active.json")
    del stage["schema_version"]
    (host.root / "active.json").write_text(json.dumps(stage))
    host.config.write_text(host.config.read_text().splitlines()[0] + "\n")
    release.initialize_channels()
    pin = release.read_state("production.json")
    assert pin["release"] == complete(1) and pin["previous"] is None
    assert not any(c[:2] in [("docker", "run"), ("docker", "stop")] for c in host.calls)
    host.verify(8080, complete(1))
    host.verify(8081, complete(1))


def test_reboot_preserves_production_independently_of_last_staging(host):
    release.apply(complete(2))
    (host.root / "release.json").write_text(json.dumps(complete(2)))
    host.running.discard("pg-api-blue")
    host.running.discard("pg-web-blue")
    release.restore_on_boot()
    assert release.read_state("production.json")["release"] == complete(1)
    host.verify(8080, complete(1))
    host.verify(8081, complete(2))


def test_low_capacity_cannot_stop_the_approved_production_slot(host, monkeypatch):
    release.apply(complete(2))

    def full():
        raise RuntimeError("Synthetic insufficient memory")

    monkeypatch.setattr(release, "require_capacity", full)
    with pytest.raises(RuntimeError, match="memory"):
        release.apply(complete(3))
    host.verify(8080, complete(1))
    assert "pg-api-blue" in host.running and "pg-api-green" not in host.running


def test_shared_database_proxy_cannot_be_changed_by_staging(host):
    changed = {**complete(2), "sql_connection": "different:region:database"}
    with pytest.raises(ValueError, match="maintenance"):
        release.apply(changed)
    assert not host.calls


def test_image_retention_includes_production_and_its_rollback():
    stage = {"release": complete(10), "previous": {"release": complete(9)}}
    prod = {"release": complete(2), "previous": {"release": complete(1)}}
    retained = release.retained_images(stage, production=prod)
    assert set(complete(1).get(k) for k in ("api_image", "web_image")) <= retained
    assert complete(2)["api_image"] in retained
    assert complete(10)["api_image"] in retained
    assert complete(9)["api_image"] not in retained
