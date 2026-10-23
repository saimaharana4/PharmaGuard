"""Rotate only PharmaGuard's database user; secret values stay in memory."""

import argparse
import base64
import json
import secrets
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession
from pharmaguard.config import secret_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    project = args.project
    prefix = f"projects/{project}/secrets"
    configs = {
        name: json.loads(secret_text(f"{prefix}/{name}/versions/1"))
        for name in ["pg-config-runtime", "pg-config-ingest"]
    }
    if any(config["db_user"] != "pharmaguard_app" for config in configs.values()):
        raise ValueError("Unexpected database identity")
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:

        def put_version(name: str, value: str) -> str:
            response = session.post(
                f"https://secretmanager.googleapis.com/v1/{prefix}/{name}:addVersion",
                json={"payload": {"data": base64.b64encode(value.encode()).decode()}},
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError("Secret version creation failed")
            return response.json()["name"]

        password = secrets.token_urlsafe(36)
        version = put_version("pg-db-password", password)
        root = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}"
        response = session.put(
            root + "/instances/pg-pharmaguard-hackathon/users",
            params={"name": "pharmaguard_app"},
            json={"name": "pharmaguard_app", "password": password},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError("Cloud SQL application-user password update failed")
        operation = response.json()["name"]
        for _ in range(60):
            response = session.get(root + "/operations/" + operation, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("error"):
                raise RuntimeError("Cloud SQL rejected the password update")
            if result["status"] == "DONE":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Cloud SQL update did not finish; inspect operation metadata")
        print("Updated application-user password; stored " + version, flush=True)
        for name, config in configs.items():
            config["secret_references"]["db_password"] = version
            print("Stored " + put_version(name, json.dumps(config)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"Database credential rotation failed ({type(exc).__name__})") from None
