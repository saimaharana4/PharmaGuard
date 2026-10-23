"""One-time secret migration. New provider keys arrive only through a private stdin pipe."""

import argparse
import base64
import json
import sys
from pathlib import Path

import google.auth
import httpx
from google.auth.transport.requests import AuthorizedSession


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    values = json.load(sys.stdin)
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    base = f"https://secretmanager.googleapis.com/v1/projects/{args.project}/secrets"

    def put(name: str, value: str, identities: list[str]) -> str:
        result = session.post(
            base, params={"secretId": name}, json={"replication": {"automatic": {}}}, timeout=30
        )
        if result.status_code not in [200, 409]:
            raise RuntimeError("Secret creation failed")
        result = session.post(
            f"{base}/{name}:addVersion",
            json={"payload": {"data": base64.b64encode(value.encode()).decode()}},
            timeout=30,
        )
        result.raise_for_status()
        resource = result.json()["name"]
        for identity in identities:
            policy = session.get(f"{base}/{name}:getIamPolicy", timeout=30)
            policy.raise_for_status()
            body = policy.json()
            binding = next(
                (
                    b
                    for b in body.setdefault("bindings", [])
                    if b["role"] == "roles/secretmanager.secretAccessor"
                ),
                None,
            )
            if binding is None:
                binding = {"role": "roles/secretmanager.secretAccessor", "members": []}
                body["bindings"].append(binding)
            member = f"serviceAccount:{identity}@{args.project}.iam.gserviceaccount.com"
            if member not in binding["members"]:
                binding["members"].append(member)
                updated = session.post(
                    f"{base}/{name}:setIamPolicy", json={"policy": body}, timeout=30
                )
                updated.raise_for_status()
        print("Stored " + resource, flush=True)
        return resource

    runtime = ["pg-runtime-sa"]
    groq = put("pg-groq-api-key", values["groq_api_key"], runtime)
    openai = put("pg-openai-api-key", values["openai_api_key"], runtime)
    models = {}
    for provider, endpoint, key in [
        ("groq", "https://api.groq.com/openai/v1/models", values["groq_api_key"]),
        ("openai", "https://api.openai.com/v1/models", values["openai_api_key"]),
    ]:
        response = httpx.get(endpoint, headers={"Authorization": "Bearer " + key}, timeout=30)
        if response.status_code == 200:
            models[provider] = {item["id"] for item in response.json()["data"]}
            print(f"Verified {provider} model-list access", flush=True)
        else:
            models[provider] = set()
            print(
                f"{provider} model discovery unavailable: HTTP {response.status_code}", flush=True
            )
    local_password = None
    env_file = Path(".env")
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("DB_PASSWORD="):
                local_password = line.split("=", 1)[1]
    if not local_password:
        raise RuntimeError("Existing local database password is required for migration")
    local_db = put("pg-local-db-password", local_password, [])
    prefix = f"projects/{args.project}/secrets"
    shared = {
        "gcp_project_id": args.project,
        "gcp_region": "asia-south1",
        "gcs_bucket": f"pharmaguard-hackathon-{args.project}",
        "qdrant_url": "https://483e4e20-6083-4d20-b872-26cf1cfe02fb.sa-east-1-0.aws.cloud.qdrant.io",
        "llm_model": "gemini-3.8-flash",
        "vertex_location": "global",
        "groq_model": next(
            (m for m in ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"] if m in models["groq"]),
            "openai/gpt-oss-120b",
        ),
        "openai_model": "gpt-4.1-mini",
        "judge_provider": "openai",
        "judge_model": "gpt-4.1" if "gpt-4.1" in models["openai"] else "gpt-4.1-mini",
        "embedding_query_model": "ncbi/MedCPT-Query-Encoder",
        "embedding_document_model": "ncbi/MedCPT-Article-Encoder",
        "embedding_query_revision": "d83a36cc6b8e3a5c5e9d9d6ba156808c1643dcbc",
        "embedding_document_revision": "d05a736da4bb84ee4057b7f7999485be6ed85465",
        "db_name": "pharmaguard",
        "db_user": "pharmaguard_app",
        "lookback_months": 24,
        "daily_request_limit": 200,
        "secret_references": {
            "db_password": f"{prefix}/pg-db-password/versions/1",
            "qdrant_api_key": f"{prefix}/pg-qdrant-api-key/versions/1",
            "groq_api_key": groq,
            "openai_api_key": openai,
        },
    }
    cloud = {
        **shared,
        "app_env": "staging",
        "raw_store": "gcs",
        "cloud_sql_connection_name": f"{args.project}:asia-south1:pg-pharmaguard-hackathon",
    }
    put("pg-config-runtime", json.dumps(cloud), runtime)
    ingest = {
        **cloud,
        "secret_references": {
            k: v
            for k, v in cloud["secret_references"].items()
            if k in ["db_password", "qdrant_api_key"]
        },
    }
    put("pg-config-ingest", json.dumps(ingest), ["pg-ingest-sa"])
    local = {
        **shared,
        "app_env": "local",
        "db_host": "127.0.0.1",
        "db_port": 5432,
        "secret_references": {**shared["secret_references"], "db_password": local_db},
    }
    local_config = put("pg-config-local", json.dumps(local), [])
    Path("config/bootstrap.local.json").write_text(
        json.dumps({"app_config_secret": local_config}, indent=2)
    )
    # Verify the migrated credential before removing the old local environment file.
    response = session.get(f"https://secretmanager.googleapis.com/v1/{local_db}:access", timeout=30)
    response.raise_for_status()
    if base64.b64decode(response.json()["payload"]["data"]).decode() != local_password:
        raise RuntimeError("Local password verification failed")
    env_file.unlink()
    print("Removed .env after verifying its database password in Secret Manager", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Secret migration failed ({type(exc).__name__}); no secret values were logged.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
