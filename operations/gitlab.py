"""GitLab CLI authentication stays in its OS keyring, never in repository files."""

import json
import os
import shutil
import subprocess
from pathlib import Path


class GitLab:
    def request(self, method: str, endpoint: str, body: dict | None = None):
        executable = shutil.which("glab")
        if not executable:
            candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/glab/glab.exe"
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            raise RuntimeError("Install GitLab CLI and authenticate with its OS keyring")
        args = [executable, "api", endpoint, "--method", method]
        if body is not None:
            args.extend(["--input", "-"])
        environment = os.environ.copy()
        environment.pop("DEBUG", None)
        result = subprocess.run(
            args,
            input=json.dumps(body) if body is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=90,
        )
        if result.returncode:
            # Do not repeat arbitrary API/error bodies or authentication material.
            raise RuntimeError(f"GitLab {method} operation failed; inspect access to {endpoint}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def graphql(self, query: str, variables: dict | None = None):
        response = self.request("POST", "graphql", {"query": query, "variables": variables or {}})
        if response.get("errors"):
            raise RuntimeError("GitLab GraphQL rejected the operation: " + str(response["errors"]))
        return response["data"]

    def pages(self, endpoint: str):
        items = []
        separator = "&" if "?" in endpoint else "?"
        for page in range(1, 100):
            batch = self.request("GET", endpoint + f"{separator}per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise RuntimeError("Project listing exceeded the supported page limit")
