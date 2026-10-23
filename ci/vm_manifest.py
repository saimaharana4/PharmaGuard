"""Write the same non-secret expected manifest for staging and human promotion."""

import json
import os
import sys
from pathlib import Path

from infra.vm.release import validate_release

FIELDS = {
    "api_image": "API_IMAGE",
    "web_image": "WEB_IMAGE",
    "sql_proxy_image": "SQL_PROXY_IMAGE",
    "runtime_config": "RUNTIME_CONFIG_REFERENCE",
    "sql_connection": "CLOUD_SQL_CONNECTION_NAME",
    "git_sha": "CI_COMMIT_SHA",
    "expires_at": "VM_EXPIRES_AT",
}


def write(path: Path) -> None:
    release = {field: os.environ[variable] for field, variable in FIELDS.items()}
    validate_release(release)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(release), encoding="utf-8")
    path.chmod(0o600)


if __name__ == "__main__":
    write(Path(sys.argv[1]))
