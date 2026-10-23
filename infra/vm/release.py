"""Run as root on the VM. Blue/green containers; no Terraform or secret payloads here."""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/opt/pharmaguard")
DIGEST = re.compile(r"^[a-z0-9.-]+/[\w./-]+@sha256:[a-f0-9]{64}$")
SLOTS = {
    "blue": (28080, "172.30.73.2", "172.30.73.3"),
    "green": (28081, "172.30.73.4", "172.30.73.5"),
}


def log(event: str, **fields) -> None:
    line = json.dumps({"timestamp": datetime.now(UTC).isoformat(), "event": event, **fields})
    print(line, flush=True)
    with (ROOT / "deployment.jsonl").open("a") as stream:
        stream.write(line + "\n")


def command(*args: str, input_text: str | None = None) -> str:
    started = time.monotonic()
    operation = " ".join(args[:2])
    log("deployment_operation_started", operation=operation)
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=900)
    if result.returncode:
        # Docker/provider errors can expose configuration; keep only operation and exit code.
        log("deployment_operation_failed", operation=args[0], exit_code=result.returncode)
        raise RuntimeError("Deployment operation failed; inspect restricted host logs")
    log(
        "deployment_operation_completed",
        operation=operation,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    return result.stdout.strip()


def metadata(path: str) -> dict:
    if path != "instance/service-accounts/default/token":
        raise ValueError("Unexpected metadata resource")
    connection = http.client.HTTPConnection("metadata.google.internal", timeout=10)
    try:
        connection.request(
            "GET", "/computeMetadata/v1/" + path, headers={"Metadata-Flavor": "Google"}
        )
        response = connection.getresponse()
        if response.status != 200 or response.getheader("Metadata-Flavor") != "Google":
            raise OSError("Metadata identity endpoint validation failed")
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError("Metadata response exceeded its size limit")
        return json.loads(body)
    finally:
        connection.close()


def candidate_json(port: int, route: str, timeout: int = 5) -> dict:
    if port not in {8080, 8081, 28080, 28081} or route not in {"ready", "version"}:
        raise ValueError("Unexpected local release probe")
    connection = http.client.HTTPConnection("127.0.0.1", port=port, timeout=timeout)
    try:
        connection.request("GET", "/api/" + route)
        response = connection.getresponse()
        if response.status != 200:
            raise OSError("Local release probe did not return HTTP 200")
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError("Local release response exceeded its size limit")
        return json.loads(body)
    finally:
        connection.close()


def wait_ready(port: int, attempts: int = 90) -> None:
    for _ in range(attempts):
        try:
            candidate_json(port, "ready")
            return
        except (OSError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError("Candidate readiness failed")


def verify_release(port: int, release: dict, attempts: int = 90) -> None:
    wait_ready(port, attempts=attempts)
    version = candidate_json(port, "version", timeout=10)
    if version.get("git_sha") != release["git_sha"]:
        raise RuntimeError("Served source does not match the recorded release")


def read_state(name: str) -> dict | None:
    path = ROOT / name
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    if state.get("slot") not in SLOTS or state.get("schema_version", 1) not in {1, 2}:
        raise ValueError("Invalid recorded release state")
    validate_release(state["release"])
    return state


def save_state(name: str, state: dict) -> None:
    pending = ROOT / (name + ".pending")
    with pending.open("w") as stream:
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    pending.chmod(0o600)
    os.replace(pending, ROOT / name)


def route_config(staging: str | None, production: str | None) -> str:
    """Only the production pin may choose the upstream for listener 8080."""
    servers = []
    for listen, slot in [(8080, production), (8081, staging)]:
        if slot is not None and slot not in SLOTS:
            raise ValueError("Invalid route slot")
        upstream = (
            f"proxy_pass http://127.0.0.1:{SLOTS[slot][0]}; "
            "proxy_set_header Host $http_host; proxy_set_header X-Forwarded-Proto https; "
            "proxy_read_timeout 95s;"
            if slot
            else "return 503;"
        )
        servers.append(
            f"server {{ listen {listen}; server_tokens off; client_max_body_size 16k; "
            f"location / {{ {upstream} }} }}"
        )
    return "\n".join(servers) + "\n"


def restore_route(config: Path, old: str | None) -> None:
    if old is None:
        config.unlink(missing_ok=True)
    else:
        config.write_text(old)
    command("nginx", "-t")
    command("systemctl", "reload", "nginx")


def initialize_channels() -> None:
    """Pin the existing legacy backend without approving a new staging release."""
    staging, production = read_state("active.json"), read_state("production.json")
    if production:
        verify_release(8080, production["release"])
        return
    if not staging or staging.get("schema_version") == 2:
        # An isolated staging-only installation has no approved production yet.
        return
    verify_release(8080, staging["release"])
    config = Path("/etc/nginx/sites-enabled/pharmaguard")
    old = config.read_text() if config.exists() else None
    try:
        config.write_text(route_config(staging["slot"], staging["slot"]))
        command("nginx", "-t")
        command("systemctl", "reload", "nginx")
        verify_release(8080, staging["release"], attempts=5)
        save_state(
            "production.json",
            {
                "schema_version": 2,
                "slot": staging["slot"],
                "release": staging["release"],
                "previous": None,
            },
        )
    except Exception:
        restore_route(config, old)
        raise
    log("production_pin_initialized", git_sha=staging["release"]["git_sha"], slot=staging["slot"])


def guard_metadata() -> None:
    check = subprocess.run(["iptables", "-nL", "DOCKER-USER"], capture_output=True)
    if check.returncode:
        command("iptables", "-N", "DOCKER-USER")
    for ip in ["172.30.73.3", "172.30.73.5"]:
        rule = ["-s", ip, "-d", "169.254.169.254/32", "-j", "REJECT"]
        check = subprocess.run(["iptables", "-C", "DOCKER-USER", *rule], capture_output=True)
        if check.returncode:
            command("iptables", "-I", "DOCKER-USER", *rule)


def install_metadata_guard() -> None:
    Path("/etc/systemd/system/pharmaguard-metadata-guard.service").write_text(
        "[Unit]\nDescription=Block web containers from VM credentials before Docker starts\n"
        "Before=docker.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\n"
        "ExecStart=/usr/bin/python3 /opt/pharmaguard/release.py --guard\n"
    )
    override = Path("/etc/systemd/system/docker.service.d")
    override.mkdir(exist_ok=True)
    (override / "pharmaguard.conf").write_text(
        "[Unit]\nRequires=pharmaguard-metadata-guard.service\n"
        "After=pharmaguard-metadata-guard.service\n"
    )
    command("systemctl", "daemon-reload")
    guard_metadata()


def retained_images(
    state: dict | None, candidate: dict | None = None, production: dict | None = None
) -> set[str]:
    """Retain production, its rollback, staging and an in-flight candidate."""
    releases = [candidate] if candidate else []
    if state:
        releases.append(state["release"])
        if not production and state.get("previous"):
            releases.append(state["previous"]["release"])
    if production:
        releases.append(production["release"])
        if production.get("previous"):
            releases.append(production["previous"]["release"])
    return {r[field] for r in releases for field in ("api_image", "web_image", "sql_proxy_image")}


def cleanup_images(
    state: dict, candidate: dict | None = None, production: dict | None = None
) -> None:
    keep = retained_images(state, candidate, production)
    repositories = {
        state["release"][field].split("@", 1)[0] for field in ("api_image", "web_image")
    }
    protected_ids = set(command("docker", "ps", "-aq").splitlines())
    # Inspect only IDs, never configuration/environment/secret-bearing Docker output.
    used_images = {
        command("docker", "inspect", "--format", "{{.Image}}", container)
        for container in protected_ids
    }
    removed = 0
    seen = set()
    for line in command(
        "docker", "image", "ls", "--digests", "--no-trunc", "--format", "{{json .}}"
    ).splitlines():
        item = json.loads(line)
        repository, digest = item["Repository"], item["Digest"]
        reference = repository + "@" + digest
        if reference in seen:
            continue
        seen.add(reference)
        if (
            repository in repositories
            and DIGEST.fullmatch(reference)
            and reference not in keep
            and item["ID"] not in used_images
        ):
            # No force, global prune or volume deletion. Other workloads remain protected.
            command("docker", "image", "rm", reference)
            removed += 1
    log("deployment_image_cleanup", removed=removed, retained_images=len(keep))


def stop_slot(slot: str) -> None:
    if slot not in SLOTS:
        raise ValueError("Invalid slot")
    running = set(command("docker", "ps", "--format", "{{.Names}}").splitlines())
    for name in ["pg-web-" + slot, "pg-api-" + slot]:
        if name in running:
            command("docker", "stop", name)


def stop_inactive(state: dict, production: dict | None = None) -> None:
    previous_slot = (state.get("previous") or {}).get("slot")
    if previous_slot not in {"blue", "green"} or previous_slot == state["slot"]:
        return
    if production and previous_slot == production["slot"]:
        return
    stop_slot(previous_slot)


def available_memory() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Cannot verify available memory")


def require_capacity() -> None:
    if shutil.disk_usage(ROOT).free < 5 * 1024**3:
        raise RuntimeError("Insufficient disk reserve for a safe candidate pull")
    if available_memory() < 4 * 1024**3:
        raise RuntimeError("Insufficient memory for overlapping application slots")


def validate_release(release: dict) -> None:
    required = {
        "api_image",
        "web_image",
        "sql_proxy_image",
        "runtime_config",
        "sql_connection",
        "git_sha",
        "expires_at",
    }
    if set(release) != required:
        raise ValueError("Unexpected release manifest fields")
    for field in ["api_image", "web_image", "sql_proxy_image"]:
        if not DIGEST.fullmatch(release[field]):
            raise ValueError("All images must be immutable digests")
    if not re.fullmatch(
        r"projects/[\w-]+/secrets/pg-config-runtime/versions/\d+", release["runtime_config"]
    ):
        raise ValueError("Use a pinned runtime config reference")
    if datetime.fromisoformat(release["expires_at"].replace("Z", "+00:00")) <= datetime.now(UTC):
        raise ValueError("Deployment window has expired; explicit extension required")
    if not re.fullmatch(r"[a-f0-9]{40}", release["git_sha"]):
        raise ValueError("Use a full source commit SHA")
    if not re.fullmatch(r"[\w-]+:[\w-]+:[\w-]+", release["sql_connection"]):
        raise ValueError("Invalid Cloud SQL connection name")


def apply(release: dict) -> None:
    validate_release(release)
    log("deployment_started", git_sha=release["git_sha"], image_digest=release["api_image"])
    state_path = ROOT / "active.json"
    previous, production = read_state("active.json"), read_state("production.json")
    if previous and not production and previous.get("schema_version") != 2:
        raise RuntimeError("Initialize isolated channels before replacing the legacy backend")
    if production and any(
        release[field] != production["release"][field]
        for field in ("sql_proxy_image", "sql_connection")
    ):
        raise ValueError("Shared SQL proxy changes require a separate maintenance operation")
    if previous:
        stop_inactive(previous, production)
        cleanup_images(previous, release, production)
    if state_path.exists() and json.loads(state_path.read_text())["release"] == release:
        install_metadata_guard()
        slot = json.loads(state_path.read_text())["slot"]
        try:
            verify_release(8081, release, attempts=30)
        except RuntimeError:
            log("deployment_existing_unhealthy", git_sha=release["git_sha"])
        else:
            log(
                "deployment_completed",
                git_sha=release["git_sha"],
                image_digest=release["api_image"],
                status="healthy",
                unchanged=True,
                slot=slot,
                channel="staging",
            )
            return
    target_slot = (
        ("green" if production["slot"] == "blue" else "blue")
        if production
        else ("green" if previous and previous["slot"] == "blue" else "blue")
    )
    if production and previous and previous["slot"] == target_slot:
        # Reuse only the unpromoted staging slot. Production must remain running.
        stop_slot(target_slot)
    require_capacity()
    token = metadata("instance/service-accounts/default/token")["access_token"]
    registry = release["api_image"].split("/")[0]
    # Temporary tmpfs Docker credential file is removed immediately after pulls.
    auth_dir = Path("/run/pharmaguard-docker-auth")
    auth_dir.mkdir(mode=0o700, exist_ok=True)
    try:
        command(
            "docker",
            "--config",
            str(auth_dir),
            "login",
            "-u",
            "oauth2accesstoken",
            "--password-stdin",
            registry,
            input_text=token,
        )
        for field in ["api_image", "web_image", "sql_proxy_image"]:
            command("docker", "--config", str(auth_dir), "pull", release[field])
    finally:
        (auth_dir / "config.json").unlink(missing_ok=True)
        auth_dir.rmdir()
    networks = command("docker", "network", "ls", "--format", "{{.Name}}").splitlines()
    if "pg-app" not in networks:
        command("docker", "network", "create", "--subnet", "172.30.73.0/24", "pg-app")
    # Install before candidates and before Docker's automatic restarts on future boots.
    install_metadata_guard()
    names = command("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
    if "pg-sql" not in names:
        command(
            "docker",
            "run",
            "-d",
            "--name",
            "pg-sql",
            "--restart",
            "unless-stopped",
            "--network",
            "pg-app",
            "--ip",
            "172.30.73.6",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--log-driver",
            "journald",
            release["sql_proxy_image"],
            "--address=0.0.0.0",
            "--port=5432",
            "--structured-logs",
            release["sql_connection"],
        )
    slot = target_slot
    if production and slot == production["slot"]:
        raise RuntimeError("Staging cannot replace the pinned production slot")
    port, api_ip, web_ip = SLOTS[slot]
    for name in [f"pg-web-{slot}", f"pg-api-{slot}"]:
        if name in names:
            command("docker", "rm", "-f", name)
    common = [
        "--restart",
        "unless-stopped",
        "--network",
        "pg-app",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:size=256m",
        "--log-driver",
        "journald",
    ]
    committed = False
    old_config = None
    route_written = False
    try:
        command(
            "docker",
            "run",
            "-d",
            "--name",
            f"pg-api-{slot}",
            *common,
            "--ip",
            api_ip,
            "--memory",
            "3500m",
            "--cpus",
            "2",
            "-e",
            "PORT=8080",
            "-e",
            "APP_CONFIG_SECRET=" + release["runtime_config"],
            "-e",
            "DB_USE_TCP=true",
            "-e",
            "DB_HOST=pg-sql",
            "-e",
            "DB_PORT=5432",
            "-e",
            "GIT_SHA=" + release["git_sha"],
            "-e",
            "OMP_NUM_THREADS=2",
            "-e",
            "MKL_NUM_THREADS=2",
            "-e",
            "HF_HUB_OFFLINE=1",
            release["api_image"],
        )
        command(
            "docker",
            "run",
            "-d",
            "--name",
            f"pg-web-{slot}",
            *common,
            "--ip",
            web_ip,
            "--memory",
            "512m",
            "--publish",
            f"127.0.0.1:{port}:8080",
            "-e",
            "PORT=8080",
            "-e",
            "API_INTERNAL_URL=http://pg-api-" + slot + ":8080",
            "-e",
            "API_AUTH_MODE=local",
            "-e",
            "COOKIE_SECURE=true",
            release["web_image"],
        )
        verify_release(port, release)
        log("deployment_candidate_ready", git_sha=release["git_sha"], slot=slot)
        config = Path("/etc/nginx/sites-enabled/pharmaguard")
        old_config = config.read_text() if config.exists() else None
        config.write_text(route_config(slot, production["slot"] if production else None))
        route_written = True
        try:
            command("nginx", "-t")
            command("systemctl", "reload", "nginx")
            verify_release(8081, release, attempts=5)
            if production:
                verify_release(8080, production["release"], attempts=5)
        except Exception:
            if old_config is not None:
                config.write_text(old_config)
                command("systemctl", "reload", "nginx")
            else:
                config.unlink(missing_ok=True)
            log("deployment_rollback", status="restored_previous_route")
            route_written = False
            raise
        save_state(
            "active.json",
            {
                "schema_version": 2,
                "slot": slot,
                "release": release,
                "previous": (
                    {"slot": previous["slot"], "release": previous["release"]} if previous else None
                ),
            },
        )
        committed = True
        # Keep previous manifest for rollback, stop idle containers to release RAM.
        stop_inactive(json.loads(state_path.read_text()), production)
        cleanup_images(json.loads(state_path.read_text()), production=production)
        log(
            "deployment_completed",
            git_sha=release["git_sha"],
            slot=slot,
            image_digest=release["api_image"],
            status="healthy",
            channel="staging",
        )
    except Exception as exc:
        if not committed:
            if route_written:
                if old_config is not None:
                    config.write_text(old_config)
                else:
                    config.unlink(missing_ok=True)
                command("systemctl", "reload", "nginx")
            # Failed candidates must not retain RAM or restart after a host reboot.
            for name in [f"pg-web-{slot}", f"pg-api-{slot}"]:
                try:
                    command("docker", "rm", "-f", name)
                except RuntimeError:
                    log("deployment_cleanup_failed", container=name)
        log("deployment_failed", git_sha=release["git_sha"], error_type=type(exc).__name__)
        raise


def promote(release: dict) -> None:
    """Called only by the approved production job, under the same host lock."""
    validate_release(release)
    staging, production = read_state("active.json"), read_state("production.json")
    if not staging or staging["release"] != release:
        raise ValueError("Approval is stale: the staged manifest no longer matches")
    slot = staging["slot"]
    for component, field in [("api", "api_image"), ("web", "web_image")]:
        image = command(
            "docker", "inspect", "--format", "{{.Config.Image}}", f"pg-{component}-{slot}"
        )
        if image != release[field]:
            raise RuntimeError("Staged container does not match the approved digest")
    verify_release(8081, release)
    if production and production["slot"] == slot and production["release"] == release:
        verify_release(8080, release)
        log("production_promoted", git_sha=release["git_sha"], slot=slot, unchanged=True)
        return
    config = Path("/etc/nginx/sites-enabled/pharmaguard")
    old = config.read_text() if config.exists() else None
    promoted = {
        "schema_version": 2,
        "slot": slot,
        "release": release,
        "previous": (
            {"slot": production["slot"], "release": production["release"]} if production else None
        ),
    }
    try:
        config.write_text(route_config(slot, slot))
        command("nginx", "-t")
        command("systemctl", "reload", "nginx")
        verify_release(8080, release, attempts=5)
        save_state("production.json", promoted)
    except Exception:
        restore_route(config, old)
        log(
            "production_promotion_failed",
            git_sha=release["git_sha"],
            status="previous_route_restored",
        )
        raise
    # Both listeners now use the approved slot. Only the other slot may stop.
    stop_inactive({"slot": slot, "previous": production}, promoted)
    cleanup_images(staging, production=promoted)
    log(
        "production_promoted",
        git_sha=release["git_sha"],
        slot=slot,
        image_digest=release["api_image"],
        status="healthy",
    )


def restore_on_boot() -> None:
    """Restore approved production independently of the last staging manifest."""
    staging, production = read_state("active.json"), read_state("production.json")
    if production:
        for name in ["pg-sql", "pg-api-" + production["slot"], "pg-web-" + production["slot"]]:
            command("docker", "start", name)
        config = Path("/etc/nginx/sites-enabled/pharmaguard")
        config.write_text(route_config(staging["slot"] if staging else None, production["slot"]))
        command("nginx", "-t")
        command("systemctl", "reload", "nginx")
        verify_release(8080, production["release"])
    else:
        initialize_channels()
    manifest = ROOT / "release.json"
    if manifest.exists():
        apply(json.loads(manifest.read_text()))


if __name__ == "__main__":
    import fcntl

    if sys.argv[1] == "--guard":
        guard_metadata()
        raise SystemExit(0)
    with (ROOT / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sys.argv[1] == "--promote":
            promote(json.loads(Path(sys.argv[2]).read_text()))
        elif sys.argv[1] == "--stage-rollback":
            initialize_channels()
            expected = json.loads(Path(sys.argv[2]).read_text())
            production = read_state("production.json")
            previous = (production or {}).get("previous")
            if not previous or previous["release"] != expected:
                raise ValueError("Rollback must match the recorded previous production release")
            apply(expected)
        elif sys.argv[1] == "--restore":
            restore_on_boot()
        else:
            initialize_channels()
            apply(json.loads(Path(sys.argv[1]).read_text()))
