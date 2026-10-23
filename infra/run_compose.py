"""Load credentials in memory, then invoke Compose without a .env file."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from google.auth import _cloud_sdk
from pharmaguard.config import load_settings

settings = load_settings()
reference = settings.app_config_secret
if not reference:
    bootstrap = Path("config/bootstrap.local.json")
    if bootstrap.is_file():
        reference = json.loads(bootstrap.read_text())["app_config_secret"]
if not reference:
    raise SystemExit("Set APP_CONFIG_SECRET to a pinned Secret Manager configuration version")
environment = os.environ.copy()
environment.update(
    DB_PASSWORD=settings.db_password.get_secret_value(),
    DB_USER=settings.db_user,
    DB_NAME=settings.db_name,
    POSTGRES_PORT=str(settings.db_port),
    QDRANT_PORT=str(urlparse(settings.qdrant_url).port or 6333),
    QDRANT_COLLECTION=settings.qdrant_collection,
    APP_CONFIG_SECRET=reference,
    ADC_PATH=_cloud_sdk.get_application_default_credentials_path(),
)
docker = "docker"
windows_path = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
if os.name == "nt" and windows_path.exists():
    docker = str(windows_path)
args = sys.argv[1:]
if args and args[0] == "config" and "--quiet" not in args:
    raise SystemExit("Use config --quiet so Compose cannot print resolved credentials")
raise SystemExit(subprocess.call([docker, "compose", *args], env=environment))
