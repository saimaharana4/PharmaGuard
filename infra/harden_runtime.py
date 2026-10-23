"""Create and verify a restricted DB login before switching the public API configuration."""

import argparse
import base64
import json
import secrets

import google.auth
from google.auth.transport.requests import AuthorizedSession
from pharmaguard.config import secret_text

from infra.provision_runtime import gcloud

BOOTSTRAP = r"""
import json
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import text
from pharmaguard.config import load_settings, secret_text
from pharmaguard.db import session_factory
try:
    settings = load_settings()
    role = 'pharmaguard_runtime'
    password = secret_text('projects/' + settings.gcp_project_id +
                           '/secrets/pg-runtime-db-password/versions/1')
    with session_factory(settings).begin() as session:
        raw = session.connection().connection.driver_connection
        with raw.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,))
            exists = cursor.fetchone()
            encrypted = raw.pgconn.encrypt_password(
                password.encode(), role.encode(), b'scram-sha-256').decode()
            command = 'ALTER ROLE' if exists else 'CREATE ROLE'
            cursor.execute(sql.SQL(command + ' {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                                   'NOINHERIT NOREPLICATION PASSWORD {}').format(
                                       sql.Identifier(role), sql.Literal(encrypted)))
            for table in ['dataset', 'active_dataset', 'source_document', 'evidence_chunk',
                          'dataset_chunk', 'entity', 'faers_report', 'faers_drug',
                          'faers_reaction', 'faers_deletion']:
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    sql.Identifier(table), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON request_budget TO {}').format(
                sql.Identifier(role)))
            cursor.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='25s'").format(
                sql.Identifier(role)))
    restricted = settings.model_copy(update={'db_user': role, 'db_password': SecretStr(password)})
    with session_factory(restricted)() as session:
        checks = session.execute(text("SELECT "
            "has_table_privilege(current_user,'faers_report','SELECT'), "
            "has_table_privilege(current_user,'faers_report','UPDATE'), "
            "has_table_privilege(current_user,'request_budget','UPDATE')")).one()
        if tuple(checks) != (True, False, True):
            raise RuntimeError('Runtime database grants did not match policy')
    print(json.dumps({'runtime_can_read_reports': True, 'runtime_can_update_reports': False,
                      'runtime_can_update_usage_budget': True}), flush=True)
except Exception as exc:
    print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}), flush=True)
    raise SystemExit(1) from None
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if "@sha256:" not in args.image:
        raise ValueError("Use an immutable image digest")
    project = args.project
    prefix = f"projects/{project}/secrets"
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:

        def store(name, value):
            result = session.post(
                f"https://secretmanager.googleapis.com/v1/{prefix}/{name}:addVersion",
                json={"payload": {"data": base64.b64encode(value.encode()).decode()}},
                timeout=30,
            )
            if result.status_code != 200:
                raise RuntimeError("Secret version creation failed")
            return result.json()["name"]

        def create(name):
            result = session.post(
                f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets",
                params={"secretId": name},
                json={"replication": {"automatic": {}}},
                timeout=30,
            )
            if result.status_code not in [200, 409]:
                raise RuntimeError("Secret creation failed")
            return result.status_code == 200

        if create("pg-runtime-db-password"):
            store("pg-runtime-db-password", secrets.token_urlsafe(36))
        else:
            # Never silently roll back a previously rotated credential.
            versions = (
                session.get(
                    f"https://secretmanager.googleapis.com/v1/{prefix}/pg-runtime-db-password/versions",
                    timeout=30,
                )
                .json()
                .get("versions", [])
            )
            if len(versions) != 1:
                raise RuntimeError("Existing runtime credential versions require explicit review")
        for identity in ["pg-runtime-sa", "pg-ingest-sa"]:
            gcloud(
                "secrets",
                "add-iam-policy-binding",
                "pg-runtime-db-password",
                "--project=" + project,
                f"--member=serviceAccount:{identity}@{project}.iam.gserviceaccount.com",
                "--role=roles/secretmanager.secretAccessor",
            )
        program = (
            "exec(__import__('base64').b64decode('"
            + base64.b64encode(BOOTSTRAP.encode()).decode()
            + "'))"
        )
        scope = ["--project=" + project, "--region=asia-south1"]
        gcloud(
            "run",
            "jobs",
            "deploy",
            "pharmaguard-db-permissions",
            *scope,
            "--image=" + args.image,
            f"--service-account=pg-ingest-sa@{project}.iam.gserviceaccount.com",
            f"--set-cloudsql-instances={project}:asia-south1:pg-pharmaguard-hackathon",
            f"--set-env-vars=APP_CONFIG_SECRET={prefix}/pg-config-ingest/versions/3",
            "--command=python",
            "--args=-c," + program,
            "--max-retries=0",
            "--task-timeout=600s",
        )
        gcloud("run", "jobs", "execute", "pharmaguard-db-permissions", *scope, "--wait")
        original = json.loads(secret_text(f"{prefix}/pg-config-runtime/versions/3"))
        runtime = {
            **original,
            "db_user": "pharmaguard_runtime",
            "secret_references": {
                **original["secret_references"],
                "db_password": f"{prefix}/pg-runtime-db-password/versions/1",
            },
        }
        runtime_version = store("pg-config-runtime", json.dumps(runtime))
        create("pg-config-evaluation")
        evaluation_version = store("pg-config-evaluation", json.dumps(original))
        gcloud(
            "secrets",
            "add-iam-policy-binding",
            "pg-config-evaluation",
            "--project=" + project,
            f"--member=serviceAccount:pg-eval-sa@{project}.iam.gserviceaccount.com",
            "--role=roles/secretmanager.secretAccessor",
        )
        gcloud(
            "secrets",
            "remove-iam-policy-binding",
            "pg-config-runtime",
            "--project=" + project,
            f"--member=serviceAccount:pg-eval-sa@{project}.iam.gserviceaccount.com",
            "--role=roles/secretmanager.secretAccessor",
        )
        gcloud(
            "run",
            "services",
            "update",
            "pharmaguard-api",
            *scope,
            "--update-env-vars=APP_CONFIG_SECRET=" + runtime_version,
        )
        gcloud(
            "secrets",
            "remove-iam-policy-binding",
            "pg-db-password",
            "--project=" + project,
            f"--member=serviceAccount:pg-runtime-sa@{project}.iam.gserviceaccount.com",
            "--role=roles/secretmanager.secretAccessor",
        )
        gcloud(
            "secrets",
            "remove-iam-policy-binding",
            "pg-runtime-db-password",
            "--project=" + project,
            f"--member=serviceAccount:pg-ingest-sa@{project}.iam.gserviceaccount.com",
            "--role=roles/secretmanager.secretAccessor",
        )
        print(
            json.dumps(
                {"runtime_config": runtime_version, "evaluation_config": evaluation_version}
            ),
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"Runtime permission setup failed ({type(exc).__name__})") from None
