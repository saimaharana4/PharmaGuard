"""Verify staging did not change the public source. Never stores cookies or tokens."""

import http.client
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

EDGE_HOSTS = frozenset(
    {
        "pharmaguard-web-dfthmgvvaa-el.a.run.app",
        "pharmaguard-vm-preview-dfthmgvvaa-el.a.run.app",
    }
)


def read_version(url: str) -> dict:
    url = url.rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in EDGE_HOSTS
        or parts.port not in {None, 443}
        or parts.username
        or parts.password
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Use an approved public HTTPS service URL")
    connection = http.client.HTTPSConnection(parts.hostname, timeout=30)
    try:
        # A fixed path and direct connection never follow redirects or use proxy env settings.
        connection.request("GET", "/api/version")
        response = connection.getresponse()
        if response.status != 200:
            raise OSError("Approved edge version check did not return HTTP 200")
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError("Edge version response exceeded its size limit")
        body = json.loads(payload)
    finally:
        connection.close()
    sha = body.get("git_sha", "") if isinstance(body, dict) else ""
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Public production did not return a verifiable source")
    return {"git_sha": sha, "app_version": body.get("app_version")}


def capture(phase: str, directory: Path = Path("deployment")) -> None:
    if phase not in {"before", "after"}:
        raise ValueError("Unknown production verification phase")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"production-{phase}.json"
    output.unlink(missing_ok=True)
    if phase == "before":
        (directory / "production-after.json").unlink(missing_ok=True)
    snapshot = read_version(os.environ["WEB_URL"])
    if phase == "after":
        before = json.loads((directory / "production-before.json").read_text())
        if before != snapshot:
            raise ValueError("Staging changed the public production source")
    output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(json.dumps({"event": f"production_verified_{phase}_staging", **snapshot}))


if __name__ == "__main__":
    capture(sys.argv[1])
