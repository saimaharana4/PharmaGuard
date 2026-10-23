"""Reject every destroy/replacement and any secret payload in the Terraform plan."""

import json
import sys
from pathlib import Path


def check(plan: dict) -> list[dict]:
    changes = []
    for item in plan.get("resource_changes", []):
        actions = item["change"]["actions"]
        if "delete" in actions:
            raise ValueError("Terraform deletion/replacement is prohibited: " + item["address"])
        if item["type"] in {"google_secret_manager_secret_version", "google_sql_database_instance"}:
            raise ValueError("Application Terraform cannot own credentials or existing Cloud SQL")
        changes.append({"address": item["address"], "actions": actions})
    return changes


if __name__ == "__main__":
    report = {"passed": True, "changes": check(json.loads(Path(sys.argv[1]).read_text()))}
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2))
