"""Create an in-memory signing key and pinned config versions; never emit secret payloads."""

import argparse
import base64
import json
import secrets
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession
from pharmaguard.config import secret_text

from infra.provision_runtime import gcloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--runtime-version", required=True, type=int)
    parser.add_argument("--local-version", required=True, type=int)
    args = parser.parse_args()
    prefix = f"projects/{args.project}/secrets"
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as client:
        response = client.post(
            f"https://secretmanager.googleapis.com/v1/{prefix}",
            params={"secretId": "pg-session-signing-key"},
            json={"replication": {"automatic": {}}},
            timeout=30,
        )
        if response.status_code not in [200, 409]:
            raise RuntimeError("Signing secret creation failed")

        def add_version(name: str, value: str) -> str:
            response = client.post(
                f"https://secretmanager.googleapis.com/v1/{prefix}/{name}:addVersion",
                json={"payload": {"data": base64.b64encode(value.encode()).decode()}},
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError("Configuration publication failed")
            return response.json()["name"]

        if response.status_code == 200:
            key_reference = add_version("pg-session-signing-key", secrets.token_urlsafe(48))
        else:
            response = client.get(
                f"https://secretmanager.googleapis.com/v1/{prefix}/pg-session-signing-key/versions",
                timeout=30,
            )
            response.raise_for_status()
            versions = [v for v in response.json().get("versions", []) if v["state"] == "ENABLED"]
            if len(versions) != 1:
                raise RuntimeError("Select a reviewed signing key version explicitly")
            key_reference = versions[0]["name"]
        references = {}
        for name, version in [
            ("pg-config-runtime", args.runtime_version),
            ("pg-config-local", args.local_version),
        ]:
            config = json.loads(secret_text(f"{prefix}/{name}/versions/{version}"))
            config["sessions_enabled"] = True
            config.setdefault("secret_references", {})["session_signing_key"] = key_reference
            references[name] = add_version(name, json.dumps(config))
    gcloud(
        "secrets",
        "add-iam-policy-binding",
        "pg-session-signing-key",
        "--project=" + args.project,
        f"--member=serviceAccount:pg-runtime-sa@{args.project}.iam.gserviceaccount.com",
        "--role=roles/secretmanager.secretAccessor",
    )
    Path(".data/session-config-references.json").write_text(json.dumps(references, indent=2))
    print(json.dumps(references))


if __name__ == "__main__":
    main()
