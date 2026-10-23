"""Dedicated evaluation identity with access limited to its models, DB, and artifact prefix."""

import argparse

from infra.provision_runtime import gcloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = args.project
    email = f"pg-eval-sa@{project}.iam.gserviceaccount.com"
    if not gcloud(
        "iam",
        "service-accounts",
        "describe",
        email,
        "--project=" + project,
        "--format=value(email)",
        allow_missing=True,
    ):
        gcloud("iam", "service-accounts", "create", "pg-eval-sa", "--project=" + project)
    member = "serviceAccount:" + email
    for role in ["roles/cloudsql.client", "roles/aiplatform.user"]:
        gcloud(
            "projects",
            "add-iam-policy-binding",
            project,
            "--member=" + member,
            "--role=" + role,
            "--condition=None",
        )
    for name in [
        "pg-config-runtime",
        "pg-db-password",
        "pg-qdrant-api-key",
        "pg-groq-api-key",
        "pg-openai-api-key",
    ]:
        gcloud(
            "secrets",
            "add-iam-policy-binding",
            name,
            "--project=" + project,
            "--member=" + member,
            "--role=roles/secretmanager.secretAccessor",
        )
    bucket = "pharmaguard-hackathon-" + project
    condition = (
        "expression=resource.name.startsWith('projects/_/buckets/"
        + bucket
        + "/objects/evaluation/'),title=pharmaguard-evaluation-artifacts"
    )
    for role in ["roles/storage.objectViewer", "roles/storage.objectCreator"]:
        gcloud(
            "storage",
            "buckets",
            "add-iam-policy-binding",
            "gs://" + bucket,
            "--project=" + project,
            "--member=" + member,
            "--role=" + role,
            "--condition=" + condition,
        )
    print("Provisioned evaluation identity with conditional evaluation-prefix storage access")


if __name__ == "__main__":
    main()
