"""Real Nginx routes with synthetic HTTP source fixtures; no corpus or provider calls."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from infra.vm.release import route_config

pytestmark = [
    pytest.mark.routing,
    pytest.mark.skipif(
        os.environ.get("RUN_ROUTING_INTEGRATION") != "1",
        reason="Run the Docker routing gate with RUN_ROUTING_INTEGRATION=1",
    ),
]
IMAGE = (
    "nginxinc/nginx-unprivileged@sha256:"
    "f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03"
)


def docker(*args):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Docker routing operation {args[0]} failed ({result.returncode})")
    return result.stdout.strip()


def configuration(staging):
    upstreams = ""
    for port, source in [(28080, "b" * 40), (28081, "c" * 40)]:
        body = json.dumps({"git_sha": source})
        upstreams += (
            f"server {{ listen 127.0.0.1:{port}; location / {{ "
            f"default_type application/json; return 200 '{body}'; }} }}\n"
        )
    return (
        "pid /tmp/nginx.pid; error_log /dev/stderr; events {}\nhttp { access_log off;\n"
        "client_body_temp_path /tmp/client; proxy_temp_path /tmp/proxy;\n"
        "fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi;\n"
        + upstreams
        + route_config(staging, "blue")
        + "}\n"
    )


def wait_source(url, expected):
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with direct.open(url + "/api/version", timeout=2) as response:
                if json.load(response)["git_sha"] == expected:
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise AssertionError("Real Nginx listener did not serve its expected source fixture")


def test_repeated_staging_route_changes_never_move_production():
    name = "pharmaguard-route-test-" + uuid4().hex[:12]
    endpoint = urlsplit(os.environ.get("DOCKER_HOST", ""))
    host = endpoint.hostname if endpoint.scheme == "tcp" else "127.0.0.1"
    bind = "127.0.0.1" if host in {"localhost", "127.0.0.1"} else "0.0.0.0"
    script = (
        "cat > /tmp/routes.conf <<'CONF'\n"
        + configuration("green")
        + ("CONF\nexec nginx -c /tmp/routes.conf -g 'daemon off;'")
    )
    created = False
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,size=16m",
            "-p",
            f"{bind}::8080",
            "-p",
            f"{bind}::8081",
            IMAGE,
            "sh",
            "-c",
            script,
        )
        created = True
        ports = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
        production = f"http://{host}:" + ports["8080/tcp"][0]["HostPort"]
        staging = f"http://{host}:" + ports["8081/tcp"][0]["HostPort"]
        wait_source(production, "b" * 40)
        wait_source(staging, "c" * 40)
        for number in range(10):
            slot = "blue" if number % 2 == 0 else "green"
            update = (
                "cat > /tmp/routes.conf <<'CONF'\n"
                + configuration(slot)
                + ("CONF\nnginx -t -c /tmp/routes.conf && nginx -s reload -c /tmp/routes.conf")
            )
            docker("exec", name, "sh", "-c", update)
            wait_source(staging, ("b" if slot == "blue" else "c") * 40)
            wait_source(production, "b" * 40)
    finally:
        if created:
            docker("rm", "-f", name)
