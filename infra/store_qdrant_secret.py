"""Read a key from a private stdin pipe, validate it, and store it in Secret Manager.

Never supply the key through command-line arguments or a repository file.
"""

import argparse
import base64
import sys

import google.auth
import httpx
from google.auth.transport.requests import AuthorizedSession


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    key = sys.stdin.read().strip()
    if not key or not args.endpoint.startswith("https://"):
        raise SystemExit("A key on stdin and an HTTPS cluster endpoint are required")
    try:
        response = httpx.get(
            args.endpoint.rstrip("/") + "/collections", headers={"api-key": key}, timeout=20
        )
        response.raise_for_status()
        print("Verified Qdrant cluster authentication")
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = AuthorizedSession(credentials)
        base = f"https://secretmanager.googleapis.com/v1/projects/{args.project}/secrets"
        secret = "pg-qdrant-api-key"
        created = session.post(
            base, params={"secretId": secret}, json={"replication": {"automatic": {}}}, timeout=30
        )
        if created.status_code not in [200, 409]:
            raise RuntimeError("Secret creation failed")
        version = session.post(
            f"{base}/{secret}:addVersion",
            json={
                "payload": {
                    "data": base64.b64encode(key.encode()).decode(),
                }
            },
            timeout=30,
        )
        version.raise_for_status()
        print("Stored secret version: " + version.json()["name"])
        for service in ["pg-runtime-sa", "pg-ingest-sa"]:
            policy = session.get(f"{base}/{secret}:getIamPolicy", timeout=30)
            policy.raise_for_status()
            body = policy.json()
            bindings = body.setdefault("bindings", [])
            member = f"serviceAccount:{service}@{args.project}.iam.gserviceaccount.com"
            binding = next(
                (b for b in bindings if b["role"] == "roles/secretmanager.secretAccessor"), None
            )
            if binding is None:
                binding = {"role": "roles/secretmanager.secretAccessor", "members": []}
                bindings.append(binding)
            if member not in binding["members"]:
                binding["members"].append(member)
                result = session.post(
                    f"{base}/{secret}:setIamPolicy", json={"policy": body}, timeout=30
                )
                result.raise_for_status()
        print("Granted secret access to the runtime and ingestion identities")
    except Exception as exc:
        print(
            f"Secret setup failed ({type(exc).__name__}). No secret value was logged.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
